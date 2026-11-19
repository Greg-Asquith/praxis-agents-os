# apps/api/services/mail_merge/resume_mail_merge.py

"""Resume a paused merge, once its mailbox can send again."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, ConflictError
from models.integrations import IntegrationConnection
from models.mail_merge import MailMerge
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.integrations.domain import CONNECTION_STATUS_ACTIVE
from services.mail_merge.domain import (
    MERGE_STATUS_PAUSED,
    MERGE_STATUS_QUEUED,
    STOP_REASON_RECONNECT,
)
from services.mail_merge.get_mail_merge import mail_merge_read
from services.mail_merge.queue_merge_send import queue_merge_send
from services.mail_merge.schemas import MailMergeRead
from services.mail_merge.utils import (
    get_merge_for_actor,
    has_merge_scopes,
    mail_merge_definition,
    move_merge,
)

_PROVIDER_LABELS = {"gmail": "Gmail", "outlook_mail": "Outlook"}


async def resume_mail_merge(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    merge_id: UUID,
) -> MailMergeRead:
    """Queues a paused merge again. The send job waits on its own for daily-limit room.

    Raises:
        ConflictError: Thrown when the merge isn't paused, or another merge is sending from
            the same mailbox.
        AppValidationError: Thrown when a merge paused for a reconnect still can't send.
    """
    merge = await get_merge_for_actor(
        db,
        actor=actor,
        workspace=workspace,
        membership=membership,
        merge_id=merge_id,
        for_update=True,
    )
    if merge.status != MERGE_STATUS_PAUSED:
        raise ConflictError(
            "Only a paused mail merge can be resumed", conflicting_resource="mail_merge"
        )
    if merge.stop_reason == STOP_REASON_RECONNECT and not await _mailbox_can_send(db, merge):
        label = _PROVIDER_LABELS.get(merge.provider_key, "the mailbox")
        raise AppValidationError(f"Reconnect {label} in Integrations, then resume.")
    try:
        async with db.begin_nested():
            move_merge(merge, MERGE_STATUS_QUEUED, now=datetime.now(UTC))
            await db.flush()
            await queue_merge_send(db, merge=merge)
    except IntegrityError:
        raise ConflictError(
            "Another mail merge is sending from this mailbox. Resume this one when it finishes.",
            conflicting_resource="mail_merge",
        ) from None
    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.MAIL_MERGE,
        resource_id=merge.id,
        actor=actor,
        details={"status": MERGE_STATUS_QUEUED},
    )
    return await mail_merge_read(db, merge)


async def _mailbox_can_send(db: AsyncSession, merge: MailMerge) -> bool:
    connection = (
        await db.get(IntegrationConnection, merge.connection_id) if merge.connection_id else None
    )
    # The same checks the send job makes, plus a sign-in the provider still accepts.
    if (
        connection is None
        or connection.deleted
        or connection.status != CONNECTION_STATUS_ACTIVE
        or connection.provider_key != merge.provider_key
        or connection.owner_user_id != merge.created_by_user_id
    ):
        return False
    return await has_merge_scopes(db, connection, mail_merge_definition(merge.provider_key))
