"""Workspace editors can share skills with every workspace."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import maintenance_async_db_session, set_session_tenant_context
from core.exceptions.auth import AuthorizationError
from models.workspace import WorkspaceRole
from services.skills import create_skill, update_skill
from services.skills.schemas import SkillCreateRequest, SkillUpdateRequest
from tests.factories import build_user, build_workspace, build_workspace_membership
from utils.content import ContentScope

pytestmark = pytest.mark.asyncio


async def _member(role: WorkspaceRole = WorkspaceRole.MEMBER) -> dict[str, object]:
    suffix = uuid4().hex
    actor = build_user(email=f"shared-skill-{suffix}@example.com")
    workspace = build_workspace(slug=f"shared-skill-{suffix[:12]}")
    membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=actor.id,
        role=role,
    )
    async with maintenance_async_db_session() as db:
        db.add_all([actor, workspace, membership])
    return {"actor": actor, "workspace": workspace, "membership": membership}


def _shared_skill(name: str) -> SkillCreateRequest:
    return SkillCreateRequest(
        name=name,
        description="Shared guidance.",
        instructions="Follow the shared workflow.",
        scope=ContentScope.PLATFORM,
    )


async def test_workspace_editor_can_share_and_revise_a_skill_but_read_only_member_cannot(
    db_session: AsyncSession,
) -> None:
    editor = await _member()
    viewer = await _member(WorkspaceRole.READ_ONLY)
    await set_session_tenant_context(db_session, workspace_id=editor["workspace"].id)

    shared = await create_skill(
        db_session,
        request=None,
        payload=_shared_skill(f"shared-{uuid4().hex[:8]}"),
        **editor,
    )
    updated = await update_skill(
        db_session,
        request=None,
        skill_id=shared.id,
        payload=SkillUpdateRequest(instructions="Revised shared workflow."),
        **editor,
    )

    assert shared.scope == ContentScope.PLATFORM
    assert updated.can_manage_platform is True
    assert updated.instructions == "Revised shared workflow."
    with pytest.raises(AuthorizationError):
        await create_skill(
            db_session,
            request=None,
            payload=_shared_skill(f"blocked-{uuid4().hex[:8]}"),
            **viewer,
        )
