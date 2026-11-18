# apps/api/tests/services/mail_merge/test_send_merge_chunk.py

"""The background sender: reconcile before any resend, send-time checks, and stop rules."""

import importlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import set_session_tenant_context
from core.exceptions.integration import (
    IntegrationFailureDisposition,
    IntegrationRateLimitError,
    IntegrationSendingLimitError,
    IntegrationValidationError,
)
from core.settings import settings
from models.email_suppression import WorkspaceEmailSuppression
from models.jobs import Job
from models.mail_merge import MailMerge, MailMergeRecipient
from models.user import User
from services.integrations import plugin as plugin_module
from services.integrations.plugin import (
    IntegrationMailMergeDefinition,
    MailMergeDelivery,
    MailMergeDraft,
    MailMergeMessage,
)
from services.jobs.domain import JOB_STATUS_PENDING, JOB_STATUS_RUNNING
from services.jobs.handlers import send_mail_merge as _registers_handler  # noqa: F401
from services.mail_merge import send_merge_chunk
from services.mail_merge.domain import MAIL_MERGE_SEND_JOB_KIND
from tests.factories import build_job, build_user, build_workspace, build_workspace_membership
from tests.factories.integrations import build_external_credential, build_integration_connection

pytestmark = pytest.mark.asyncio

# The package exports a function with the module's name, so import the module itself.
chunk_module = importlib.import_module("services.mail_merge.send_merge_chunk")

COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"


class FakeMailbox:
    """A provider mailbox: drafts, what was really sent, and errors to raise on send."""

    def __init__(self) -> None:
        self.drafts: dict[str, str] = {}
        self.created: list[MailMergeMessage] = []
        self.sent: list[str] = []
        self.send_errors: list[Exception] = []
        self.crash_after_send = False

    async def create_draft(self, message: MailMergeMessage) -> MailMergeDraft:
        draft_id = f"draft-{len(self.created)}"
        self.created.append(message)
        self.drafts[draft_id] = "unsent"
        return MailMergeDraft(draft_id=draft_id, thread_id=f"thread-{draft_id}")

    async def send_draft(self, draft: MailMergeDraft) -> MailMergeDelivery:
        if self.send_errors:
            raise self.send_errors.pop(0)
        self.drafts[draft.draft_id] = "sent"
        self.sent.append(draft.draft_id)
        if self.crash_after_send:
            # The worker dies after the provider accepted the email, before Praxis records it.
            raise RuntimeError("worker died")
        return MailMergeDelivery(state="sent", provider_message_id=f"message-{draft.draft_id}")

    async def check_draft(self, draft: MailMergeDraft) -> MailMergeDelivery:
        state = self.drafts.get(draft.draft_id, "unknown")
        if state == "sent":
            return MailMergeDelivery(state="sent", provider_message_id=f"message-{draft.draft_id}")
        return MailMergeDelivery(state=state)  # type: ignore[arg-type]


@pytest.fixture
def mailbox(monkeypatch: pytest.MonkeyPatch) -> FakeMailbox:
    fake = FakeMailbox()
    definition = IntegrationMailMergeDefinition(
        open_sender=lambda db, connection: fake, required_scopes=frozenset({COMPOSE_SCOPE})
    )
    monkeypatch.setitem(
        plugin_module.PROVIDER_PLUGINS, "gmail", SimpleNamespace(mail_merge=definition)
    )

    async def no_wait() -> None:
        return None

    monkeypatch.setattr(chunk_module, "_wait_between_sends", no_wait)
    return fake


async def _merge(
    db: AsyncSession,
    *,
    emails: list[str],
    scopes: tuple[str, ...] = (COMPOSE_SCOPE,),
    status: str = "queued",
) -> tuple[MailMerge, Job]:
    user = build_user(email=f"sender-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"merge-{uuid4().hex[:8]}")
    credential = build_external_credential(provider_key="gmail", granted_scopes=list(scopes))
    db.add_all([user, workspace, credential])
    await db.flush()
    db.add(build_workspace_membership(workspace_id=workspace.id, user_id=user.id))
    connection = build_integration_connection(
        credential=credential, user=user, owner_user_id=user.id
    )
    db.add(connection)
    await db.flush()
    merge = MailMerge(
        workspace_id=workspace.id,
        created_by_user_id=user.id,
        connection_id=connection.id,
        tool_call_id=f"call-{uuid4().hex[:8]}",
        provider_key="gmail",
        sender_address="sasha@example.org",
        subject_template="Hello {{first_name}}",
        body_template="<p>Hi {{first_name}}</p>",
        content_fingerprint="0" * 64,
        status=status,
    )
    db.add(merge)
    await db.flush()
    db.add_all(
        MailMergeRecipient(
            workspace_id=workspace.id,
            merge_id=merge.id,
            position=position,
            email=email,
            fields={"email": email, "first_name": email.split("@")[0].title()},
        )
        for position, email in enumerate(emails)
    )
    await db.flush()
    await set_session_tenant_context(db, workspace_id=workspace.id)
    return merge, await _claimed_job(db, merge)


async def _claimed_job(db: AsyncSession, merge: MailMerge) -> Job:
    """A send job as the runner holds it: running, with a live lease."""
    job = build_job(
        kind=MAIL_MERGE_SEND_JOB_KIND,
        workspace_id=merge.workspace_id,
        subject_type="mail_merge",
        subject_id=merge.id,
        payload={"merge_id": str(merge.id)},
        status=JOB_STATUS_RUNNING,
    )
    job.lease_token = uuid4()
    job.lock_expires_at = datetime.now(UTC) + timedelta(minutes=5)
    db.add(job)
    await db.commit()
    return job


async def _rows(db: AsyncSession, merge: MailMerge) -> list[MailMergeRecipient]:
    return list(
        (
            await db.scalars(
                select(MailMergeRecipient)
                .where(MailMergeRecipient.merge_id == merge.id)
                .order_by(MailMergeRecipient.position)
                .execution_options(populate_existing=True)
            )
        ).all()
    )


async def _next_job(db: AsyncSession, merge: MailMerge) -> Job | None:
    return await db.scalar(
        select(Job).where(Job.subject_id == merge.id, Job.status == JOB_STATUS_PENDING)
    )


async def test_a_crash_after_the_provider_accepted_a_send_is_reconciled_without_a_second_send(
    db_session: AsyncSession, mailbox: FakeMailbox
) -> None:
    merge, job = await _merge(db_session, emails=["dana@example.com"])
    mailbox.crash_after_send = True

    with pytest.raises(RuntimeError, match="worker died"):
        await send_merge_chunk(db_session, job)
    await db_session.rollback()
    [row] = await _rows(db_session, merge)
    assert (row.status, row.provider_draft_id) == ("sending", "draft-0")

    mailbox.crash_after_send = False
    await send_merge_chunk(db_session, await _claimed_job(db_session, merge))

    [row] = await _rows(db_session, merge)
    await db_session.refresh(merge)
    assert (row.status, row.provider_message_id) == ("sent", "message-draft-0")
    assert mailbox.sent == ["draft-0"]
    assert merge.status == "completed"


async def test_a_sending_row_the_provider_cant_account_for_is_unverified_and_never_resent(
    db_session: AsyncSession, mailbox: FakeMailbox
) -> None:
    merge, job = await _merge(db_session, emails=["dana@example.com", "kai@example.com"])
    first, _ = await _rows(db_session, merge)
    first.status = "sending"
    first.attempted_at = datetime.now(UTC)
    first.provider_draft_id = "deleted-by-hand"
    await db_session.commit()

    await send_merge_chunk(db_session, job)

    first, second = await _rows(db_session, merge)
    assert (first.status, second.status) == ("unverified", "sent")
    assert [message.to for message in mailbox.created] == ["kai@example.com"]


async def test_an_address_added_to_do_not_email_after_approval_is_skipped_at_send_time(
    db_session: AsyncSession, mailbox: FakeMailbox
) -> None:
    merge, job = await _merge(db_session, emails=["dana@example.com", "kai@example.com"])
    db_session.add(
        WorkspaceEmailSuppression(
            workspace_id=merge.workspace_id,
            email="kai@example.com",
            match_key="kai@example.com",
            reason="Asked not to be contacted",
        )
    )
    await db_session.commit()

    await send_merge_chunk(db_session, job)

    statuses = [row.status for row in await _rows(db_session, merge)]
    assert statuses == ["sent", "skipped"]
    assert [message.to for message in mailbox.created] == ["dana@example.com"]


async def test_a_mailbox_at_its_cap_waits_for_room_and_sends_nothing(
    db_session: AsyncSession, mailbox: FakeMailbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "MAIL_MERGE_DAILY_CAP_GOOGLE_WORKSPACE", 1)
    merge, job = await _merge(db_session, emails=["dana@example.com", "kai@example.com"])
    first, _ = await _rows(db_session, merge)
    sent_at = datetime.now(UTC) - timedelta(hours=2)
    first.status, first.attempted_at, first.sent_at = "sent", sent_at, sent_at
    await db_session.commit()

    await send_merge_chunk(db_session, job)

    assert mailbox.created == []
    next_job = await _next_job(db_session, merge)
    assert next_job is not None
    assert next_job.run_after == pytest.approx(
        sent_at + timedelta(hours=24), abs=timedelta(seconds=1)
    )


async def test_the_daily_sending_limit_pauses_the_merge_and_the_row_waits(
    db_session: AsyncSession, mailbox: FakeMailbox
) -> None:
    merge, job = await _merge(db_session, emails=["dana@example.com"])
    mailbox.send_errors.append(
        IntegrationSendingLimitError(
            "limit", failure_disposition=IntegrationFailureDisposition.REJECTED
        )
    )

    await send_merge_chunk(db_session, job)

    [row] = await _rows(db_session, merge)
    await db_session.refresh(merge)
    assert (merge.status, merge.stop_reason) == ("paused", "daily_limit")
    assert (row.status, row.provider_draft_id) == ("pending", "draft-0")
    assert await _next_job(db_session, merge) is None


async def test_a_rate_limited_row_waits_for_retry_after_then_checks_its_draft_before_sending(
    db_session: AsyncSession, mailbox: FakeMailbox
) -> None:
    merge, job = await _merge(db_session, emails=["dana@example.com"])
    mailbox.send_errors.append(
        IntegrationRateLimitError(
            "slow down",
            retry_after_seconds=120,
            failure_disposition=IntegrationFailureDisposition.REJECTED,
        )
    )

    await send_merge_chunk(db_session, job)

    [row] = await _rows(db_session, merge)
    assert row.status == "pending"
    next_job = await _next_job(db_session, merge)
    assert next_job.run_after == pytest.approx(
        datetime.now(UTC) + timedelta(seconds=120), abs=timedelta(seconds=10)
    )

    await db_session.delete(next_job)
    await send_merge_chunk(db_session, await _claimed_job(db_session, merge))

    [row] = await _rows(db_session, merge)
    assert row.status == "sent"
    assert (len(mailbox.created), mailbox.sent) == (1, ["draft-0"])


async def test_a_deactivated_sender_stops_the_merge_before_the_next_send(
    db_session: AsyncSession, mailbox: FakeMailbox
) -> None:
    merge, job = await _merge(db_session, emails=["dana@example.com"], status="sending")
    sender = await db_session.get(User, merge.created_by_user_id)
    sender.is_active = False
    await db_session.commit()

    await send_merge_chunk(db_session, job)

    await db_session.refresh(merge)
    [row] = await _rows(db_session, merge)
    assert (merge.status, merge.stop_reason) == ("stopped", "sender_removed")
    assert row.status == "pending"
    assert mailbox.created == []


async def test_a_gmail_connection_without_draft_permission_pauses_for_reconnect(
    db_session: AsyncSession, mailbox: FakeMailbox
) -> None:
    merge, job = await _merge(
        db_session,
        emails=["dana@example.com"],
        scopes=("https://www.googleapis.com/auth/gmail.send",),
    )

    await send_merge_chunk(db_session, job)

    await db_session.refresh(merge)
    assert (merge.status, merge.stop_reason) == ("paused", "reconnect")
    assert mailbox.created == []


async def test_five_failures_in_a_row_stop_the_merge(
    db_session: AsyncSession, mailbox: FakeMailbox
) -> None:
    emails = [f"person{index}@example.com" for index in range(6)]
    merge, job = await _merge(db_session, emails=emails)
    mailbox.send_errors.extend(
        IntegrationValidationError(
            "rejected", failure_disposition=IntegrationFailureDisposition.REJECTED
        )
        for _ in range(6)
    )

    await send_merge_chunk(db_session, job)

    await db_session.refresh(merge)
    statuses = [row.status for row in await _rows(db_session, merge)]
    assert (merge.status, merge.stop_reason) == ("stopped", "repeated_failures")
    assert statuses == ["failed"] * 5 + ["pending"]
