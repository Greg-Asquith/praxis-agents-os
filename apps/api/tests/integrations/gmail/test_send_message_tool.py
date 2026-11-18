# apps/api/tests/integrations/gmail/test_send_message_tool.py

"""The Do Not Email check on Gmail sends, at execution time."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry
from sqlalchemy.ext.asyncio import AsyncSession

from integrations.gmail.tools.send_message import gmail_send_message
from models.email_suppression import WorkspaceEmailSuppression
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry
from tests.factories import build_workspace

pytestmark = pytest.mark.asyncio


async def test_listed_cc_refuses_the_whole_send_and_names_only_the_address(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = build_workspace(slug=f"gmail-guard-{uuid4().hex[:8]}")
    db_session.add(workspace)
    await db_session.flush()
    db_session.add(
        WorkspaceEmailSuppression(
            workspace_id=workspace.id,
            email="dana@example.com",
            match_key="dana@example.com",
            reason="PRIVATE_REASON_SENTINEL",
        )
    )
    await db_session.flush()
    provider_send = AsyncMock()
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr("integrations.gmail.tools.send_message.gmail_client", AsyncMock())
    monkeypatch.setattr("integrations.gmail.tools.send_message.send_message", provider_send)
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    mailbox = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="gmail",
        resource_type="gmail_mailbox",
        external_id="sender@example.com",
        display_name="sender@example.com",
        connection_id=uuid4(),
        connection_label="Gmail",
        connection_status="active",
        write_allowed=True,
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(mailbox,)),
            db=db_session,
            workspace=workspace,
            agent=SimpleNamespace(id=uuid4(), name="Mail agent"),
            run=SimpleNamespace(id=uuid4(), user_id=uuid4()),
        ),
        tool_name="gmail_send_message",
        tool_call_id="call-1",
    )

    result = await gmail_send_message(
        ctx,
        to=["kai@example.com"],
        subject="Catch up",
        body_html="<p>Hello</p>",
        cc=["Dana@Example.com"],
    )

    entry = result["results"][0]
    assert entry["status"] == "error"
    assert entry["error_code"] == "do_not_email"
    assert "dana@example.com" in entry["error_message"]
    assert "PRIVATE_REASON_SENTINEL" not in str(result)
    provider_send.assert_not_awaited()
    assert str(audit.await_args.kwargs["status"]) == "failure"


async def test_recipient_with_a_display_name_is_rejected_before_the_list_check() -> None:
    ctx = SimpleNamespace(deps=SimpleNamespace(db=None))

    with pytest.raises(ModelRetry):
        await gmail_send_message(
            ctx,
            to=["kai@example.com"],
            subject="Catch up",
            body_html="<p>Hello</p>",
            bcc=["Dana <dana@example.com>"],
        )
