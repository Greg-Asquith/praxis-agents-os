# apps/api/services/workspaces/provisioning.py

"""
Personal workspace provisioning for new and existing users.

Every user must have at least one workspace. This service auto-creates a
personal workspace during signup or on first login for users that lack one.
"""

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event

logger = logging.getLogger(__name__)


async def provision_personal_workspace(db: AsyncSession, user: User) -> Workspace:
    """Auto-create a personal workspace for a user.

    Idempotent — returns the existing personal workspace if one already exists.
    """
    # Lock the user row to serialise concurrent personal workspace provisioning for
    # the same user.  Two simultaneous calls (e.g. login + signup race) would
    # otherwise both pass the existence check and create duplicate workspaces.
    await db.execute(select(User).where(User.id == user.id).with_for_update())

    # Guard: check if user already owns a personal workspace
    result = await db.execute(
        select(Workspace)
        .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
        .where(
            WorkspaceMembership.user_id == user.id,
            WorkspaceMembership.deleted == False,  # noqa: E712
            Workspace.is_personal == True,  # noqa: E712
            Workspace.deleted == False,  # noqa: E712
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        if user.default_workspace_id is None:
            user.default_workspace_id = existing.id
            logger.info(
                "Repaired default workspace for user %s with existing personal workspace %s",
                user.id,
                existing.id,
            )
        return existing

    # Generate a unique slug, guarded against cross-user UUID-prefix collisions
    # (same-user races are serialised by the FOR UPDATE lock above).
    base_slug = f"personal-{str(user.id)[:8]}"
    workspace: Workspace | None = None
    for counter in range(1, 11):
        candidate_slug = base_slug if counter == 1 else f"{base_slug}-{counter}"
        candidate = Workspace(
            slug=candidate_slug,
            name="My Workspace",
            is_personal=True,
            status="active",
        )
        db.add(candidate)
        try:
            async with db.begin_nested():
                await db.flush([candidate])
            workspace = candidate
            break
        except IntegrityError:
            db.expunge(candidate)
            continue

    if workspace is None:
        raise RuntimeError(
            f"Could not generate a unique personal workspace slug after 10 attempts "
            f"for user {user.id}"
        )

    await db.flush()

    membership = WorkspaceMembership(
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
    )
    db.add(membership)

    # Set as user's default workspace only if they don't already have one
    if user.default_workspace_id is None:
        user.default_workspace_id = workspace.id

    logger.info(
        "Provisioned personal workspace %s (%s) for user %s",
        workspace.id,
        workspace.slug,
        user.id,
    )

    await record_workspace_audit_event(
        db,
        request=None,
        workspace_id=workspace.id,
        action=AuditAction.CREATE,
        resource_type=AuditResourceType.WORKSPACE,
        resource_id=workspace.id,
        actor=user,
        details={"slug": workspace.slug, "is_personal": True, "role": "owner"},
    )

    return workspace
