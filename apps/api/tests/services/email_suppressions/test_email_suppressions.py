# apps/api/tests/services/email_suppressions/test_email_suppressions.py

"""Adding to the Do Not Email list and the check every send path calls."""

from uuid import uuid4

import pytest
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.audit_event import AuditEvent
from models.email_suppression import WorkspaceEmailSuppression
from services.audit_events import AuditResourceType
from services.email_suppressions import add_email_suppressions, find_suppressed_recipients
from services.email_suppressions.schemas import EmailSuppressionAddRequest
from tests.factories import build_user, build_workspace

pytestmark = pytest.mark.asyncio

REQUEST = Request({"type": "http", "method": "POST", "path": "/", "headers": []})


async def _workspace(db: AsyncSession):
    user = build_user(email=f"suppressions-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"suppressions-{uuid4().hex[:8]}")
    db.add_all([user, workspace])
    await db.flush()
    return user, workspace


async def test_paste_reports_added_listed_and_invalid_with_one_audit_event_per_addition(
    db_session: AsyncSession,
) -> None:
    user, workspace = await _workspace(db_session)
    db_session.add(
        WorkspaceEmailSuppression(
            workspace_id=workspace.id,
            email="kai@example.com",
            match_key="kai@example.com",
            reason="Unsubscribed",
        )
    )
    await db_session.flush()

    result = await add_email_suppressions(
        db_session,
        request=REQUEST,
        actor=user,
        workspace=workspace,
        payload=EmailSuppressionAddRequest(
            addresses=[
                " Dana@Example.com",
                "KAI+news@example.com",
                "not an address",
                "dana@example.com",
            ],
            reason="Asked not to be contacted",
        ),
    )

    assert [entry.email for entry in result.added] == ["dana@example.com"]
    assert result.already_listed == ["kai+news@example.com"]
    assert result.invalid == ["not an address"]
    events = list(
        await db_session.scalars(
            select(AuditEvent).where(
                AuditEvent.workspace_id == workspace.id,
                AuditEvent.resource_type == AuditResourceType.EMAIL_SUPPRESSION.value,
            )
        )
    )
    assert [event.details for event in events] == [
        {"email": "dana@example.com", "reason": "Asked not to be contacted"}
    ]


async def test_check_matches_tagged_and_gmail_dot_variants_only_in_the_listing_workspace(
    db_session: AsyncSession,
) -> None:
    user, listing = await _workspace(db_session)
    _other_user, other = await _workspace(db_session)
    await add_email_suppressions(
        db_session,
        request=REQUEST,
        actor=user,
        workspace=listing,
        payload=EmailSuppressionAddRequest(
            addresses=["dana@example.com", "d.lee+shop@gmail.com"],
            reason="Asked not to be contacted",
        ),
    )
    addresses = [
        "kai@example.com",
        " Dana+News@EXAMPLE.com ",
        "dlee@googlemail.com",
        "d.ana@example.com",
    ]

    assert await find_suppressed_recipients(
        db_session, workspace_id=listing.id, addresses=addresses
    ) == ["dana+news@example.com", "dlee@googlemail.com"]
    assert (
        await find_suppressed_recipients(db_session, workspace_id=other.id, addresses=addresses)
        == []
    )
