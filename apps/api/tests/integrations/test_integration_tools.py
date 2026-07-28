# apps/api/tests/integrations/test_integration_tools.py

"""Shared integration-tool registry and fan-out invariants."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.exceptions.integration import IntegrationAuthError
from integrations.airtable.tools import TOOL_DEFINITIONS as AIRTABLE_TOOL_DEFINITIONS
from integrations.bigquery.tools import TOOL_DEFINITIONS as BIGQUERY_TOOL_DEFINITIONS
from integrations.gmail.tools import TOOL_DEFINITIONS
from integrations.gmail.tools.search_messages import gmail_search_messages
from integrations.gmail.tools.send_message import gmail_send_message
from integrations.gmail.tools.utils import run_audited_operation
from integrations.google_ads.settings import google_ads_settings
from integrations.google_ads.tools import TOOL_DEFINITIONS as GOOGLE_ADS_TOOL_DEFINITIONS
from models.agent import Agent
from models.agent_run import AgentRun
from models.audit_event import AuditEvent
from models.conversation import Conversation
from models.user import User
from models.workspace import Workspace
from services.agent_runs import create_agent_run
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.envelope import RunEnvelope
from services.agents.runtime.sinks import CollectingSink
from services.agents.runtime.tools.contract import TOOL_EFFECT_SCOPE_EXTERNAL
from services.agents.runtime.tools.permissions import is_tool_allowed
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry
from tests.factories import build_user, build_workspace


def test_full_integration_tool_contract_matrix_and_schemas() -> None:
    definitions = {
        definition.name: definition
        for definition in (
            *TOOL_DEFINITIONS,
            *GOOGLE_ADS_TOOL_DEFINITIONS,
            *AIRTABLE_TOOL_DEFINITIONS,
            *BIGQUERY_TOOL_DEFINITIONS,
        )
    }
    expected = {
        "gmail_search_messages": ("read", "internal", "auto", False),
        "gmail_read_message": ("read", "internal", "auto", False),
        "gmail_send_message": ("write", "external", "approval", True),
        "google_ads_list_accounts": ("read", "internal", "auto", False),
        "google_ads_run_report": ("read", "internal", "auto", False),
        "google_ads_update_campaign_status": ("write", "external", "approval", True),
        "airtable_list_records": ("read", "internal", "auto", False),
        "airtable_get_record": ("read", "internal", "auto", False),
        "airtable_create_record": ("write", "external", "approval", True),
        "airtable_update_record": ("write", "external", "approval", True),
        "bigquery_list_tables": ("read", "internal", "auto", False),
        "bigquery_get_table_schema": ("read", "internal", "auto", False),
        "bigquery_run_query": ("read", "internal", "auto", False),
    }
    assert set(definitions) == set(expected)
    denylisted = {
        "account_id",
        "base_id",
        "connection_id",
        "connection_label",
        "customer_id",
        "integration_resource_id",
        "mailbox",
        "principal",
        "resource_id",
    }
    for name, (effect, scope, policy, requires_write) in expected.items():
        definition = definitions[name]
        assert (
            definition.effect,
            definition.effect_scope,
            definition.default_policy,
            definition.integration_binding.requires_write,
        ) == (effect, scope, policy, requires_write)
        schema = definition.to_pydantic_tool().function_schema.json_schema
        assert denylisted.isdisjoint(schema["properties"])
        assert definition.presentation.running_label
        assert definition.presentation.completed_label
        assert definition.presentation.failed_label


def test_gmail_tool_contract_matrix_and_schemas() -> None:
    definitions = {definition.name: definition for definition in TOOL_DEFINITIONS}
    assert set(definitions) == {
        "gmail_search_messages",
        "gmail_read_message",
        "gmail_send_message",
    }
    assert definitions["gmail_search_messages"].effect == "read"
    assert definitions["gmail_read_message"].effect == "read"
    send = definitions["gmail_send_message"]
    assert send.effect == "write"
    assert send.effect_scope == TOOL_EFFECT_SCOPE_EXTERNAL
    assert send.default_policy == "approval"
    assert send.integration_binding is not None and send.integration_binding.requires_write

    denylisted = {
        "account_id",
        "base_id",
        "connection_id",
        "connection_label",
        "customer_id",
        "integration_resource_id",
        "mailbox",
        "principal",
        "resource_id",
    }
    for definition in definitions.values():
        schema = definition.to_pydantic_tool().function_schema.json_schema
        assert denylisted.isdisjoint(schema["properties"])
        assert definition.presentation.running_label
        assert definition.presentation.completed_label
        assert definition.presentation.failed_label


def test_google_ads_tool_contract_matrix_and_schemas(monkeypatch) -> None:
    definitions = {definition.name: definition for definition in GOOGLE_ADS_TOOL_DEFINITIONS}
    assert set(definitions) == {
        "google_ads_list_accounts",
        "google_ads_run_report",
        "google_ads_update_campaign_status",
    }
    assert definitions["google_ads_list_accounts"].effect == "read"
    assert definitions["google_ads_run_report"].effect == "read"
    spend = definitions["google_ads_update_campaign_status"]
    assert spend.effect == "write"
    assert spend.effect_scope == TOOL_EFFECT_SCOPE_EXTERNAL
    assert spend.default_policy == "approval"
    assert spend.supports_auto is False
    assert spend.allowed_policies() == frozenset({"approval"})
    assert spend.integration_binding is not None
    assert spend.integration_binding.requires_write is True

    denylisted = {
        "account_id",
        "base_id",
        "connection_id",
        "connection_label",
        "customer_id",
        "integration_resource_id",
        "mailbox",
        "principal",
        "resource_id",
    }
    for definition in definitions.values():
        schema = definition.to_pydantic_tool().function_schema.json_schema
        assert denylisted.isdisjoint(schema["properties"])
        assert definition.presentation.running_label
        assert definition.presentation.completed_label
        assert definition.presentation.failed_label

    monkeypatch.setattr(google_ads_settings, "GOOGLE_ADS_DEVELOPER_TOKEN", None)
    assert all(not is_tool_allowed(item, workspace=None) for item in definitions.values())


async def test_write_gating_fails_closed_without_provider_call(monkeypatch) -> None:
    entry = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="gmail",
        resource_type="gmail_mailbox",
        external_id="owner@example.com",
        display_name="owner@example.com",
        connection_id=uuid4(),
        connection_label="Work",
        connection_status="active",
        write_allowed=False,
    )
    deps = SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry,)))
    ctx = SimpleNamespace(deps=deps)
    provider_call = AsyncMock()
    audit = AsyncMock()
    monkeypatch.setattr("integrations.gmail.tools.send_message.send_message", provider_call)
    monkeypatch.setattr(
        "integrations.gmail.tools.send_message.record_gmail_operation_audit",
        audit,
    )

    result = await gmail_send_message(
        ctx,
        to=["recipient@example.com"],
        subject="Subject",
        body_text="Body",
    )

    assert result["results"][0]["error_code"] == "write_not_permitted"
    provider_call.assert_not_awaited()
    audit.assert_awaited_once()
    assert audit.await_args.kwargs["error_code"] == "write_not_permitted"


async def test_client_setup_failure_is_audited(monkeypatch) -> None:
    entry = _entry(write_allowed=True)
    deps = SimpleNamespace(
        active_context=ResolvedActiveContext(entries=(entry,)),
        workspace=SimpleNamespace(id=uuid4()),
        agent=SimpleNamespace(id=uuid4()),
        run=SimpleNamespace(id=uuid4()),
    )
    ctx = SimpleNamespace(deps=deps)
    audit = AsyncMock()
    monkeypatch.setattr(
        "integrations.gmail.tools.search_messages.gmail_client",
        AsyncMock(side_effect=IntegrationAuthError("expired", provider_key="gmail")),
    )
    monkeypatch.setattr(
        "integrations.gmail.tools.utils.record_integration_operation_audit_event",
        audit,
    )

    result = await gmail_search_messages(ctx, query="is:unread")

    assert result["results"][0]["error_code"] == "IntegrationAuthError"
    audit.assert_awaited_once()
    assert audit.await_args.kwargs["error_code"] == "IntegrationAuthError"


async def test_fan_out_preserves_mixed_success_and_failure(monkeypatch) -> None:
    entries = tuple(_entry(write_allowed=True, external_id=value) for value in ("one", "two"))
    deps = SimpleNamespace(
        active_context=ResolvedActiveContext(entries=entries),
        workspace=SimpleNamespace(id=uuid4()),
        agent=SimpleNamespace(id=uuid4()),
        run=SimpleNamespace(id=uuid4()),
    )
    ctx = SimpleNamespace(deps=deps)
    monkeypatch.setattr(
        "integrations.gmail.tools.search_messages.gmail_client",
        lambda _ctx, entry: _async_value(entry.external_id),
    )

    async def provider_search(client, **_kwargs):
        if client == "two":
            raise IntegrationAuthError("expired", provider_key="gmail")
        return {"messages": [], "total": 0}

    monkeypatch.setattr(
        "integrations.gmail.tools.search_messages.search_messages",
        provider_search,
    )
    monkeypatch.setattr(
        "integrations.gmail.tools.utils.record_integration_operation_audit_event",
        AsyncMock(),
    )

    result = await gmail_search_messages(ctx, query="is:unread")

    assert [item["status"] for item in result["results"]] == ["success", "error"]
    assert result["results"][1]["error_code"] == "IntegrationAuthError"


async def test_audited_operation_records_external_reference_without_content(monkeypatch) -> None:
    audit = AsyncMock()
    monkeypatch.setattr(
        "integrations.gmail.tools.utils.record_integration_operation_audit_event",
        audit,
    )
    entry = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="gmail",
        resource_type="gmail_mailbox",
        external_id="owner@example.com",
        display_name="owner@example.com",
        connection_id=uuid4(),
        connection_label="Work",
        connection_status="active",
        write_allowed=True,
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        )
    )

    async def execute():
        return {"message_id": "sent-1", "body": "must-not-enter-audit"}

    result = await run_audited_operation(
        ctx,
        entry,
        tool_name="gmail_send_message",
        operation="send_message",
        execute=execute,
        external_ref_from_result=lambda value: value["message_id"],
    )

    assert result["message_id"] == "sent-1"
    kwargs = audit.await_args.kwargs
    assert kwargs["external_ref"] == "sent-1"
    assert "body" not in kwargs


def test_gmail_availability_fails_closed_without_oauth_client(monkeypatch) -> None:
    from integrations.gmail.settings import gmail_settings

    definition = next(item for item in TOOL_DEFINITIONS if item.name == "gmail_search_messages")
    monkeypatch.setattr(gmail_settings, "GMAIL_OAUTH_CLIENT_ID", "")
    assert is_tool_allowed(definition, workspace=None) is False
    monkeypatch.setattr(gmail_settings, "GMAIL_OAUTH_CLIENT_ID", "configured")
    assert is_tool_allowed(definition, workspace=None) is True


async def test_tool_fan_out_commits_one_audit_row_per_entry(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch,
) -> None:
    context = await _committed_runtime_context(committed_db_session_factory)
    entries = tuple(_entry(write_allowed=True, external_id=value) for value in ("one", "two"))
    try:
        async with committed_db_session_factory() as db:
            user = await db.get(User, context.user_id)
            workspace = await db.get(Workspace, context.workspace_id)
            agent = await db.get(Agent, context.agent_id)
            conversation = await db.get(Conversation, context.conversation_id)
            run = await db.get(AgentRun, context.run_id)
            assert all((user, workspace, agent, conversation, run))
            deps = RuntimeDeps(
                db=db,
                user=user,
                workspace=workspace,
                conversation=conversation,
                agent=agent,
                run=run,
                sink=CollectingSink(run_id=run.id, conversation_id=conversation.id),
                envelope=RunEnvelope(principal="interactive"),
                active_context=ResolvedActiveContext(entries=entries),
            )
            ctx = SimpleNamespace(deps=deps)
            monkeypatch.setattr(
                "integrations.gmail.tools.search_messages.gmail_client",
                lambda _ctx, entry: _async_value(entry.external_id),
            )

            async def provider_search(_client, **_kwargs):
                return {"messages": [], "total": 0}

            monkeypatch.setattr(
                "integrations.gmail.tools.search_messages.search_messages",
                provider_search,
            )
            result = await gmail_search_messages(ctx, query="audit")
            assert len(result["results"]) == 2

        async with committed_db_session_factory() as db:
            rows = list(
                (
                    await db.scalars(
                        select(AuditEvent).where(
                            AuditEvent.workspace_id == context.workspace_id,
                            AuditEvent.tool_name == "gmail_search_messages",
                            AuditEvent.details["run_id"].astext == str(context.run_id),
                        )
                    )
                ).all()
            )
        assert len(rows) == 2
        assert {row.details["external_id"] for row in rows} == {"one", "two"}
        assert all("body" not in row.details for row in rows)
    finally:
        await _delete_committed_runtime_context(committed_db_session_factory, context)


def _entry(*, write_allowed: bool, external_id: str = "owner@example.com"):
    return ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="gmail",
        resource_type="gmail_mailbox",
        external_id=external_id,
        display_name=external_id,
        connection_id=uuid4(),
        connection_label="Work",
        connection_status="active",
        write_allowed=write_allowed,
    )


async def _async_value(value):
    return value


async def _committed_runtime_context(session_factory):
    async with session_factory() as db:
        user = build_user(email=f"gmail-audit-{uuid4().hex}@example.com")
        workspace = build_workspace(slug=f"gmail-audit-{uuid4().hex[:8]}")
        db.add_all([user, workspace])
        await db.flush()
        agent = Agent(
            name="Gmail Audit Agent",
            slug=f"gmail-audit-{uuid4().hex[:8]}",
            instructions="Use Gmail safely.",
            workspace_id=workspace.id,
            created_by=user.id,
            model_provider="openai",
            model="gpt-5.4-mini",
            tool_names=[],
        )
        db.add(agent)
        await db.flush()
        conversation = Conversation(
            user_id=user.id,
            workspace_id=workspace.id,
            created_by=user.id,
            active_agent_id=agent.id,
        )
        db.add(conversation)
        await db.flush()
        run = await create_agent_run(
            db,
            conversation_id=conversation.id,
            agent_id=agent.id,
            workspace_id=workspace.id,
            user_id=user.id,
            trigger="interactive",
        )
        await db.commit()
        return SimpleNamespace(
            user_id=user.id,
            workspace_id=workspace.id,
            agent_id=agent.id,
            conversation_id=conversation.id,
            run_id=run.id,
        )


async def _delete_committed_runtime_context(session_factory, context) -> None:
    async with session_factory() as db:
        await db.execute(delete(AuditEvent).where(AuditEvent.workspace_id == context.workspace_id))
        await db.execute(delete(AgentRun).where(AgentRun.id == context.run_id))
        await db.execute(delete(Conversation).where(Conversation.id == context.conversation_id))
        await db.execute(delete(Agent).where(Agent.id == context.agent_id))
        await db.execute(delete(User).where(User.id == context.user_id))
        await db.execute(delete(Workspace).where(Workspace.id == context.workspace_id))
        await db.commit()
