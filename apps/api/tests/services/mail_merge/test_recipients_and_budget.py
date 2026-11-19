# apps/api/tests/services/mail_merge/test_recipients_and_budget.py

"""Checking a merge's recipients before approval, and the mailbox's rolling daily budget."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.email_suppression import WorkspaceEmailSuppression
from models.mail_merge import MailMerge, MailMergeRecipient, MailMergeTestSend
from services.mail_merge import MailAccountKind, check_mail_merge, get_send_budget
from tests.factories import build_user, build_workspace
from tests.factories.integrations import build_external_credential, build_integration_connection

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


async def test_rows_are_skipped_for_sender_duplicates_and_do_not_email_but_invalid_ones_are_flagged(
    db_session: AsyncSession,
) -> None:
    workspace = build_workspace(slug=f"merge-{uuid4().hex[:8]}")
    db_session.add(workspace)
    await db_session.flush()
    db_session.add(
        WorkspaceEmailSuppression(
            workspace_id=workspace.id,
            email="kai@example.com",
            match_key="kai@example.com",
            reason="Asked not to be contacted",
        )
    )
    await db_session.flush()

    check = await check_mail_merge(
        db_session,
        workspace_id=workspace.id,
        sender_address="Sasha@example.com",
        subject="Hello {{first_name}}",
        body_html="<p>Hi {{first_name}}</p>",
        fallbacks={},
        rows=[
            {"email": "dana@example.com", "first_name": "Dana"},
            {"email": " DANA@Example.com", "first_name": "Dana"},
            {"email": "sasha@example.com", "first_name": "Sasha"},
            {"email": "kai+news@example.com", "first_name": "Kai"},
            {"email": "not an address", "first_name": "Lee"},
            {"email": "", "first_name": "Quinn"},
            {"email": "alex@example.com", "first_name": None},
        ],
    )

    assert [(row.email, row.status, row.skip_reason) for row in check.recipients] == [
        ("dana@example.com", "ready", None),
        ("dana@example.com", "skipped", "duplicate"),
        ("sasha@example.com", "skipped", "sender"),
        ("kai+news@example.com", "skipped", "do_not_email"),
        ("not an address", "needs_attention", None),
        ("", "needs_attention", None),
        ("alex@example.com", "needs_attention", None),
    ]


async def test_budget_counts_merge_and_test_attempts_in_the_last_24_hours_and_says_when_a_send_fits_again(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "MAIL_MERGE_DAILY_CAP_GMAIL_PERSONAL", 4)
    user = build_user(email=f"merge-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"merge-{uuid4().hex[:8]}")
    credential = build_external_credential(provider_key="gmail")
    db_session.add_all([user, workspace, credential])
    await db_session.flush()
    connection = build_integration_connection(
        credential=credential, user=user, owner_user_id=user.id
    )
    db_session.add(connection)
    await db_session.flush()
    merge = MailMerge(
        workspace_id=workspace.id,
        connection_id=connection.id,
        tool_call_id="call-1",
        provider_key="gmail",
        sender_address="sasha@gmail.com",
        subject_template="Hello",
        body_template="<p>Hi</p>",
        content_fingerprint="0" * 64,
        status="sending",
    )
    db_session.add(merge)
    await db_session.flush()
    attempts = {
        "old@example.com": NOW - timedelta(hours=25),
        "a@example.com": NOW - timedelta(hours=20),
        "b@example.com": NOW - timedelta(hours=10),
        "c@example.com": NOW - timedelta(hours=1),
    }
    db_session.add_all(
        MailMergeRecipient(
            workspace_id=workspace.id,
            merge_id=merge.id,
            position=position,
            email=email,
            status="unverified" if email == "c@example.com" else "sent",
            attempted_at=attempted_at,
        )
        for position, (email, attempted_at) in enumerate(attempts.items())
    )
    db_session.add(
        MailMergeRecipient(
            workspace_id=workspace.id,
            merge_id=merge.id,
            position=9,
            email="pending@example.com",
        )
    )
    db_session.add(
        MailMergeTestSend(
            workspace_id=workspace.id,
            connection_id=connection.id,
            tool_call_id="call-2",
            content_fingerprint="1" * 64,
            attempted_at=NOW - timedelta(hours=2),
        )
    )
    await db_session.flush()

    budget = await get_send_budget(
        db_session, connection_id=connection.id, kind=MailAccountKind.GMAIL_PERSONAL, now=NOW
    )

    assert (budget.used, budget.remaining) == (4, 0)
    assert budget.frees_at == NOW + timedelta(hours=4)
