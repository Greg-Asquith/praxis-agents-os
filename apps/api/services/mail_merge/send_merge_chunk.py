# apps/api/services/mail_merge/send_merge_chunk.py

"""Send the next chunk of a mail merge from its sender's own mailbox.

Each email is sent through a draft whose IDs are committed before the send. A row left
`sending` by a crash, a timeout, or a lost lease is reconciled from those IDs and never
sent again blindly: a draft still waiting returns to `pending`, and a row the provider
can't account for becomes `unverified`.
"""

import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import set_session_tenant_context
from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationCredentialUnavailableError,
    IntegrationError,
    IntegrationFailureDisposition,
    IntegrationPermissionError,
    IntegrationRateLimitError,
    IntegrationSendingLimitError,
)
from core.settings import settings
from models.integrations import IntegrationConnection
from models.jobs import Job
from models.mail_merge import MailMerge, MailMergeRecipient
from services.audit_events import AuditAction, AuditActorType, AuditResourceType, AuditStatus
from services.audit_events.operations import record_operation_audit_event
from services.email_suppressions import find_suppressed_recipients
from services.integrations.plugin import (
    IntegrationMailMergeDefinition,
    MailMergeDelivery,
    MailMergeDraft,
    MailMergeMessage,
    MailMergeSender,
)
from services.integrations.utils import integration_failure_code
from services.jobs.domain import JOB_STATUS_RUNNING
from services.mail_merge.budget import MailAccountKind, get_send_budget
from services.mail_merge.domain import (
    MERGE_STATUS_COMPLETED,
    MERGE_STATUS_PAUSED,
    MERGE_STATUS_QUEUED,
    MERGE_STATUS_SENDING,
    MERGE_STATUS_STOPPED,
    RECIPIENT_STATUS_FAILED,
    RECIPIENT_STATUS_PENDING,
    RECIPIENT_STATUS_SENDING,
    RECIPIENT_STATUS_SENT,
    RECIPIENT_STATUS_SKIPPED,
    RECIPIENT_STATUS_UNVERIFIED,
    STOP_REASON_DAILY_LIMIT,
    STOP_REASON_PLATFORM_QUOTA,
    STOP_REASON_RECONNECT,
    STOP_REASON_REPEATED_FAILURES,
    STOP_REASON_SENDER_REMOVED,
    can_transition_merge,
)
from services.mail_merge.queue_merge_send import queue_merge_send
from services.mail_merge.render import MergeTemplate, render_merge_email
from services.mail_merge.utils import (
    connection_account_kind,
    has_merge_scopes,
    mail_merge_definition,
    move_merge,
    move_recipient,
)
from services.workspaces.utils import get_active_membership

logger = logging.getLogger(__name__)

# One job sends at most this many emails, then queues the next, so no job runs for long.
CHUNK_MAX_SENDS = 25
CHUNK_MAX_SECONDS = 8 * 60
MAX_RATE_LIMIT_WAIT = timedelta(minutes=15)
DEFAULT_RATE_LIMIT_WAIT = timedelta(minutes=1)
MAX_FAILURES_IN_A_ROW = 5
# Spreads sends so they don't land at exact intervals.
SEND_JITTER = 0.3

_SETTLED_STATUSES = (RECIPIENT_STATUS_SENT, RECIPIENT_STATUS_FAILED, RECIPIENT_STATUS_UNVERIFIED)


@dataclass(frozen=True)
class _ChunkEnd:
    """Why this chunk stops: queue the next one, move the merge, or neither."""

    run_after: datetime | None = None
    merge_status: str | None = None
    stop_reason: str | None = None


@dataclass(frozen=True)
class _Claim:
    row: MailMergeRecipient
    message: MailMergeMessage


async def send_merge_chunk(db: AsyncSession, job: Job) -> None:
    """Sends up to one chunk of a queued or sending merge, then queues the next chunk."""
    merge_id = _payload_merge_id(job)
    if merge_id is None or job.workspace_id is None:
        logger.warning(
            "Skipping mail merge job with invalid payload", extra={"job_id": str(job.id)}
        )
        return
    merge = await db.scalar(
        select(MailMerge)
        .where(MailMerge.id == merge_id, MailMerge.workspace_id == job.workspace_id)
        .with_for_update()
    )
    if merge is None or merge.status not in (MERGE_STATUS_QUEUED, MERGE_STATUS_SENDING):
        await db.commit()
        return
    chunk = _MergeChunk(db, job, merge)
    end = await chunk.run()
    await chunk.finish(end)


class _MergeChunk:
    def __init__(self, db: AsyncSession, job: Job, merge: MailMerge) -> None:
        self.db = db
        self.job = job
        self.merge = merge
        self.sender: MailMergeSender | None = None

    async def run(self) -> _ChunkEnd:
        end = await self._start()
        if end is not None:
            return end
        end = await self._reconcile_interrupted()
        if end is not None:
            return end
        started = monotonic()
        sends = 0
        while sends < CHUNK_MAX_SENDS and monotonic() - started < CHUNK_MAX_SECONDS:
            if sends:
                await _wait_between_sends()
            claim = await self._claim_next()
            if isinstance(claim, _ChunkEnd):
                return claim
            sends += 1
            end = await self._deliver(claim)
            if end is not None:
                return end
        return _ChunkEnd(run_after=_now() + _send_interval())

    async def finish(self, end: _ChunkEnd) -> None:
        """Applies the chunk's outcome under the merge lock and queues the next chunk."""
        merge = await self._lock_merge()
        # The operator may have paused or cancelled the merge since; their choice stands.
        if end.merge_status is not None and can_transition_merge(merge.status, end.merge_status):
            move_merge(merge, end.merge_status, now=_now(), stop_reason=end.stop_reason)
        if end.run_after is not None and merge.status == MERGE_STATUS_SENDING:
            await queue_merge_send(self.db, merge=merge, run_after=end.run_after)
        await self.db.commit()

    async def _start(self) -> _ChunkEnd | None:
        """Checks the sender and mailbox before any send, then opens the provider sender."""
        merge = self.merge
        if merge.created_by_user_id is None or not await self._sender_is_member():
            return _ChunkEnd(
                merge_status=MERGE_STATUS_STOPPED, stop_reason=STOP_REASON_SENDER_REMOVED
            )
        # The sender's personal connection is visible only as that user.
        await set_session_tenant_context(
            self.db, workspace_id=merge.workspace_id, user_id=merge.created_by_user_id
        )
        # A provider turned off for this deployment raises, so the job fails and stops the merge.
        definition = mail_merge_definition(merge.provider_key)
        connection = await self._usable_connection(definition)
        if connection is None:
            return _ChunkEnd(merge_status=MERGE_STATUS_PAUSED, stop_reason=STOP_REASON_RECONNECT)
        if merge.status == MERGE_STATUS_QUEUED:
            move_merge(merge, MERGE_STATUS_SENDING, now=_now())
        await self.db.commit()
        try:
            self.sender = definition.open_sender(self.db, connection)
        except IntegrationError:
            return _ChunkEnd(merge_status=MERGE_STATUS_PAUSED, stop_reason=STOP_REASON_RECONNECT)
        return None

    async def _usable_connection(
        self, definition: IntegrationMailMergeDefinition
    ) -> IntegrationConnection | None:
        merge = self.merge
        connection = (
            await self.db.get(IntegrationConnection, merge.connection_id)
            if merge.connection_id is not None
            else None
        )
        if (
            connection is None
            or connection.deleted
            or connection.provider_key != merge.provider_key
            or connection.owner_user_id != merge.created_by_user_id
        ):
            return None
        if not await has_merge_scopes(self.db, connection, definition):
            return None
        return connection

    async def _reconcile_interrupted(self) -> _ChunkEnd | None:
        """Settles rows an earlier attempt left `sending`, from the IDs stored before the send."""
        rows = (
            await self.db.scalars(
                select(MailMergeRecipient)
                .where(
                    MailMergeRecipient.merge_id == self.merge.id,
                    MailMergeRecipient.status == RECIPIENT_STATUS_SENDING,
                )
                .order_by(MailMergeRecipient.position)
            )
        ).all()
        await self.db.commit()
        for row in rows:
            if row.provider_draft_id is None:
                # It stopped before its draft existed, so nothing was sent.
                await self._return_to_pending(row, "interrupted")
                continue
            try:
                delivery = await self._sender().check_draft(_draft(row))
            except IntegrationError as exc:
                return await self._after_failure(row, exc, settle_failure=False)
            if delivery.state == "unsent":
                # The next claim checks the draft again before sending it.
                await self._return_to_pending(row, "interrupted")
            else:
                await self._settle(row, delivery)
        return None

    async def _claim_next(self) -> _Claim | _ChunkEnd:
        """Runs the checks before a send, then marks the next row `sending` and commits."""
        if not await self._lease_held():
            await self.db.commit()
            return _ChunkEnd()
        merge = await self._lock_merge()
        if merge.status != MERGE_STATUS_SENDING:
            # Paused or cancelled by the operator.
            await self.db.commit()
            return _ChunkEnd()
        if not await self._sender_is_member():
            await self.db.commit()
            return _ChunkEnd(
                merge_status=MERGE_STATUS_STOPPED, stop_reason=STOP_REASON_SENDER_REMOVED
            )
        budget = await get_send_budget(
            self.db,
            connection_id=merge.connection_id,
            kind=await self._account_kind(),
            now=_now(),
        )
        if budget.remaining <= 0:
            await self.db.commit()
            return _ChunkEnd(run_after=budget.frees_at or _now() + DEFAULT_RATE_LIMIT_WAIT)
        while (row := await self._next_pending_row()) is not None:
            if await self._on_do_not_email(row):
                move_recipient(row, RECIPIENT_STATUS_SKIPPED)
                row.error_code = "do_not_email"
                await self.db.commit()
                continue
            return await self._mark_sending(row)
        remaining = await self.db.scalar(
            select(MailMergeRecipient.id)
            .where(
                MailMergeRecipient.merge_id == merge.id,
                MailMergeRecipient.status == RECIPIENT_STATUS_SENDING,
            )
            .limit(1)
        )
        await self.db.commit()
        if remaining is not None:
            # Another attempt holds a row; check again after it settles.
            return _ChunkEnd(run_after=_now() + _send_interval())
        return _ChunkEnd(merge_status=MERGE_STATUS_COMPLETED)

    async def _mark_sending(self, row: MailMergeRecipient) -> _Claim | _ChunkEnd:
        merge = self.merge
        rendered = render_merge_email(
            MergeTemplate(
                subject=merge.subject_template,
                body_html=merge.body_template,
                fallbacks=merge.fallbacks or {},
            ),
            row.fields or {},
        )
        move_recipient(row, RECIPIENT_STATUS_SENDING)
        row.attempted_at = _now()
        await self._audit(row, AuditStatus.PENDING)
        if rendered.email is None:
            # Approval renders every row first, so only an edited stored row gets here.
            return await self._fail(row, "render_failed")
        await self.db.commit()
        return _Claim(
            row=row,
            message=MailMergeMessage(
                to=row.email, subject=rendered.email.subject, body_html=rendered.email.body_html
            ),
        )

    async def _deliver(self, claim: _Claim) -> _ChunkEnd | None:
        row = claim.row
        sender = self._sender()
        try:
            if row.provider_draft_id is None:
                draft = await sender.create_draft(claim.message)
                await self._store_draft(row, draft)
            else:
                draft = _draft(row)
                # A draft from an earlier, rejected attempt; it may have been sent by hand since.
                delivery = await sender.check_draft(draft)
                if delivery.state != "unsent":
                    await self._settle(row, delivery)
                    return None
        except IntegrationError as exc:
            return await self._after_failure(row, exc)
        try:
            delivery = await sender.send_draft(draft)
        except IntegrationError as exc:
            if exc.failure_disposition == IntegrationFailureDisposition.AMBIGUOUS:
                return await self._after_unclear_send(row, draft)
            return await self._after_failure(row, exc)
        await self._settle(row, delivery)
        return None

    async def _after_unclear_send(
        self, row: MailMergeRecipient, draft: MailMergeDraft
    ) -> _ChunkEnd | None:
        """Asks the provider what happened to a send whose response was lost."""
        try:
            delivery = await self._sender().check_draft(draft)
        except IntegrationError:
            # The row stays `sending`; the next chunk reconciles it first.
            return _ChunkEnd(run_after=_now() + _send_interval())
        if delivery.state == "unsent":
            # The draft is still waiting, so the send failed; it isn't retried in a loop.
            return await self._fail(row, "send_failed")
        await self._settle(row, delivery)
        return None

    async def _after_failure(
        self, row: MailMergeRecipient, exc: IntegrationError, *, settle_failure: bool = True
    ) -> _ChunkEnd | None:
        """Applies the stop rules. A rejected request sent nothing, so the row can wait."""
        if isinstance(exc, IntegrationSendingLimitError):
            await self._return_to_pending(row, STOP_REASON_DAILY_LIMIT)
            return _ChunkEnd(merge_status=MERGE_STATUS_PAUSED, stop_reason=STOP_REASON_DAILY_LIMIT)
        if isinstance(exc, IntegrationRateLimitError) and exc.error_code == "platform_quota":
            await self._return_to_pending(row, STOP_REASON_PLATFORM_QUOTA)
            return _ChunkEnd(
                merge_status=MERGE_STATUS_STOPPED, stop_reason=STOP_REASON_PLATFORM_QUOTA
            )
        if isinstance(exc, (IntegrationRateLimitError, IntegrationCredentialUnavailableError)):
            await self._return_to_pending(row, "rate_limited")
            return _ChunkEnd(run_after=_now() + _rate_limit_wait(exc))
        if isinstance(exc, (IntegrationAuthError, IntegrationPermissionError)):
            await self._return_to_pending(row, STOP_REASON_RECONNECT)
            return _ChunkEnd(merge_status=MERGE_STATUS_PAUSED, stop_reason=STOP_REASON_RECONNECT)
        if not settle_failure:
            # A failed check proves nothing about the earlier send; the row waits for another.
            return _ChunkEnd(run_after=_now() + _send_interval())
        return await self._fail(row, integration_failure_code(exc))

    async def _fail(self, row: MailMergeRecipient, error_code: str) -> _ChunkEnd | None:
        move_recipient(row, RECIPIENT_STATUS_FAILED)
        row.error_code = error_code[:64]
        await self._audit(row, AuditStatus.FAILURE, error_code=row.error_code)
        await self.db.commit()
        if await self._failing_repeatedly():
            return _ChunkEnd(
                merge_status=MERGE_STATUS_STOPPED, stop_reason=STOP_REASON_REPEATED_FAILURES
            )
        return None

    async def _settle(self, row: MailMergeRecipient, delivery: MailMergeDelivery) -> None:
        if delivery.state == "sent":
            move_recipient(row, RECIPIENT_STATUS_SENT)
            row.sent_at = _now()
            row.provider_message_id = delivery.provider_message_id or row.provider_message_id
            row.message_id_header = delivery.message_id_header or row.message_id_header
            await self._audit(row, AuditStatus.SUCCESS, external_ref=row.provider_message_id)
        else:
            # Never sent again automatically: a missed email is fixable, a duplicate isn't.
            move_recipient(row, RECIPIENT_STATUS_UNVERIFIED)
            await self._audit(row, AuditStatus.UNVERIFIED)
        await self.db.commit()

    async def _store_draft(self, row: MailMergeRecipient, draft: MailMergeDraft) -> None:
        """Commits the draft's IDs before the send, so a crash after it can be reconciled."""
        row.provider_draft_id = draft.draft_id
        row.provider_thread_id = draft.thread_id
        row.message_id_header = draft.message_id_header
        await self.db.commit()

    async def _return_to_pending(self, row: MailMergeRecipient, reason: str) -> None:
        move_recipient(row, RECIPIENT_STATUS_PENDING)
        await self._audit(row, AuditStatus.FAILURE, error_code=reason)
        await self.db.commit()

    async def _failing_repeatedly(self) -> bool:
        recent = (
            await self.db.scalars(
                select(MailMergeRecipient.status)
                .where(
                    MailMergeRecipient.merge_id == self.merge.id,
                    MailMergeRecipient.status.in_(_SETTLED_STATUSES),
                )
                .order_by(MailMergeRecipient.attempted_at.desc())
                .limit(MAX_FAILURES_IN_A_ROW)
            )
        ).all()
        await self.db.commit()
        return len(recent) == MAX_FAILURES_IN_A_ROW and all(
            status == RECIPIENT_STATUS_FAILED for status in recent
        )

    async def _next_pending_row(self) -> MailMergeRecipient | None:
        return await self.db.scalar(
            select(MailMergeRecipient)
            .where(
                MailMergeRecipient.merge_id == self.merge.id,
                MailMergeRecipient.status == RECIPIENT_STATUS_PENDING,
            )
            .order_by(MailMergeRecipient.position)
            .limit(1)
            .with_for_update(skip_locked=True)
        )

    async def _on_do_not_email(self, row: MailMergeRecipient) -> bool:
        """Calls the Do Not Email guard at send time, so an address listed after approval is skipped."""
        listed = await find_suppressed_recipients(
            self.db, workspace_id=self.merge.workspace_id, addresses=[row.email]
        )
        return bool(listed)

    async def _lease_held(self) -> bool:
        held = await self.db.scalar(
            select(Job.id).where(
                Job.id == self.job.id,
                Job.status == JOB_STATUS_RUNNING,
                Job.lease_token == self.job.lease_token,
                Job.lock_expires_at > _now(),
            )
        )
        return held is not None

    async def _sender_is_member(self) -> bool:
        membership = await get_active_membership(
            self.db, workspace_id=self.merge.workspace_id, user_id=self.merge.created_by_user_id
        )
        return membership is not None

    async def _account_kind(self) -> MailAccountKind:
        connection = await self.db.get(IntegrationConnection, self.merge.connection_id)
        return connection_account_kind(
            connection,
            provider_key=self.merge.provider_key,
            sender_address=self.merge.sender_address,
        )

    async def _lock_merge(self) -> MailMerge:
        await self.db.refresh(self.merge, with_for_update=True)
        return self.merge

    async def _audit(
        self,
        row: MailMergeRecipient,
        status: AuditStatus,
        *,
        error_code: str | None = None,
        external_ref: str | None = None,
    ) -> None:
        """Records one email's attempt or outcome in the same transaction as its status."""
        merge = self.merge
        await record_operation_audit_event(
            self.db,
            workspace_id=merge.workspace_id,
            action=AuditAction.EXECUTE,
            resource_type=AuditResourceType.MAIL_MERGE,
            resource_id=merge.id,
            actor_type=AuditActorType.SYSTEM,
            actor_display="Mail merge",
            status=status,
            requested_by_user_id=merge.created_by_user_id,
            summary=f"Mail merge {merge.id} sent to recipient {row.position + 1}: {status}",
            details={
                "recipient_id": str(row.id),
                "provider_key": merge.provider_key,
                "connection_id": str(merge.connection_id) if merge.connection_id else None,
                "provider_operation": "send_merge_message",
                "external_ref": external_ref,
                "error_code": error_code,
            },
        )

    def _sender(self) -> MailMergeSender:
        if self.sender is None:
            raise RuntimeError("The mail merge sender isn't open")
        return self.sender


def _draft(row: MailMergeRecipient) -> MailMergeDraft:
    return MailMergeDraft(
        draft_id=row.provider_draft_id or "",
        thread_id=row.provider_thread_id,
        message_id_header=row.message_id_header,
    )


def _payload_merge_id(job: Job) -> UUID | None:
    try:
        return UUID(str((job.payload or {}).get("merge_id")))
    except ValueError:
        return None


def _rate_limit_wait(exc: IntegrationError) -> timedelta:
    seconds = getattr(exc, "retry_after_seconds", None)
    if seconds is None:
        return DEFAULT_RATE_LIMIT_WAIT
    return min(timedelta(seconds=seconds), MAX_RATE_LIMIT_WAIT)


def _send_interval() -> timedelta:
    base = settings.MAIL_MERGE_SEND_INTERVAL_SECONDS
    jitter = random.uniform(1 - SEND_JITTER, 1 + SEND_JITTER)  # noqa: S311 - not security-sensitive
    return timedelta(seconds=base * jitter)


async def _wait_between_sends() -> None:
    await asyncio.sleep(_send_interval().total_seconds())


def _now() -> datetime:
    return datetime.now(UTC)
