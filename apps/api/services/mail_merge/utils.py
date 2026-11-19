# apps/api/services/mail_merge/utils.py

"""Guarded status moves for merges and their recipients, who may act on a merge, and the
provider's merge seam."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.auth import AuthorizationError
from core.exceptions.general import ConflictError, NotFoundError
from models.integrations import ExternalCredential, IntegrationConnection
from models.mail_merge import MailMerge, MailMergeRecipient
from models.user import User
from models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from services.integrations.plugin import PROVIDER_PLUGINS, IntegrationMailMergeDefinition
from services.mail_merge.budget import MailAccountKind, mail_account_kind
from services.mail_merge.domain import (
    FINAL_MERGE_STATUSES,
    can_transition_merge,
    can_transition_recipient,
)

_WORKSPACE_ADMIN_ROLES = frozenset({WorkspaceRole.ADMIN.value, WorkspaceRole.OWNER.value})


async def get_merge_for_actor(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    merge_id: UUID,
    for_update: bool = False,
) -> MailMerge:
    """Returns the merge when the actor created it or administers the workspace.

    Raises:
        NotFoundError: Thrown when the workspace has no such merge.
        AuthorizationError: Thrown for anyone else, since the rows name every recipient.
    """
    query = select(MailMerge).where(
        MailMerge.id == merge_id, MailMerge.workspace_id == workspace.id
    )
    merge = await db.scalar(query.with_for_update() if for_update else query)
    if merge is None:
        raise NotFoundError(
            "Mail merge not found", resource_type="mail_merge", resource_id=str(merge_id)
        )
    if merge.created_by_user_id != actor.id and membership.role not in _WORKSPACE_ADMIN_ROLES:
        raise AuthorizationError(
            "Only the person who sent this mail merge, or an admin, can do this"
        )
    return merge


def move_merge(
    merge: MailMerge, target: str, *, now: datetime, stop_reason: str | None = None
) -> None:
    """Moves a merge the caller has locked to target, or raises ConflictError."""
    if not can_transition_merge(merge.status, target):
        raise ConflictError(
            f"Cannot move mail merge from {merge.status!r} to {target!r}",
            conflicting_resource="mail_merge",
            details={"mail_merge_id": str(merge.id), "from": merge.status, "to": target},
        )
    merge.status = target
    merge.stop_reason = stop_reason
    if target in FINAL_MERGE_STATUSES:
        merge.finished_at = now


def move_recipient(row: MailMergeRecipient, target: str) -> None:
    """Moves a recipient row the caller has locked to target, or raises ConflictError."""
    if not can_transition_recipient(row.status, target):
        raise ConflictError(
            f"Cannot move mail merge recipient from {row.status!r} to {target!r}",
            conflicting_resource="mail_merge_recipient",
            details={"recipient_id": str(row.id), "from": row.status, "to": target},
        )
    row.status = target


def mail_merge_definition(provider_key: str) -> IntegrationMailMergeDefinition:
    """Returns the provider's merge sender, or raises when the provider is turned off."""
    plugin = PROVIDER_PLUGINS.get(provider_key)
    if plugin is None or plugin.mail_merge is None:
        raise RuntimeError(f"Mail merges aren't available for {provider_key}")
    return plugin.mail_merge


async def has_merge_scopes(
    db: AsyncSession,
    connection: IntegrationConnection,
    definition: IntegrationMailMergeDefinition,
) -> bool:
    """Checks the connection was granted every scope merge sends need."""
    granted = await db.scalar(
        select(ExternalCredential.granted_scopes).where(
            ExternalCredential.id == connection.credential_id
        )
    )
    return definition.required_scopes <= set(granted or ())


def connection_account_kind(
    connection: IntegrationConnection | None, *, provider_key: str, sender_address: str
) -> MailAccountKind:
    """Returns the mailbox kind, reading an Outlook tenant from the connection's sign-in."""
    metadata = (connection.provider_metadata if connection is not None else None) or {}
    tenant_id = metadata.get("tenant_id")
    return mail_account_kind(
        provider_key=provider_key,
        sender_address=sender_address,
        tenant_id=tenant_id if isinstance(tenant_id, str) else None,
    )
