"""Notion write approvals through the production suspension and resume path."""

from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

from pydantic_ai import Tool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from integrations.notion.references import NotionDataSourceReference, NotionPageReference
from integrations.notion.tools.create_page import DEFINITION as CREATE_PAGE_DEFINITION
from integrations.notion.tools.update_page_properties import (
    DEFINITION as UPDATE_PROPERTIES_DEFINITION,
)
from models.agent_run import AgentRun
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.agent_runs.resume_run_stream import _build_deferred_tool_results
from services.agent_runs.schemas import AgentRunResumeDecision
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.code_mode.stubs import CodeModeCatalog
from services.agents.runtime.tools.code_mode import RUN_WORKFLOW_TOOL_NAME, build_run_workflow_tool
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.audit_events import AuditStatus
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.execution import _run_authorized_entries
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)


async def test_direct_create_resume_reauthorizes_edited_parent_and_records_exact_evidence(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch,
) -> None:
    definition = replace(CREATE_PAGE_DEFINITION, availability_check=lambda: True)
    monkeypatch.setitem(RUNTIME_TOOL_CATALOG, definition.name, definition)
    _force_only_direct_tool(monkeypatch, definition)
    entry = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="notion",
        resource_type="notion_workspace",
        external_id="workspace-1",
        display_name="Product workspace",
        connection_id=uuid4(),
        connection_label="Product",
        connection_status="active",
        write_allowed=True,
    )
    page = NotionPageReference(
        workspace_id="workspace-1",
        page_id="page-1",
        label="Launch plan",
        description="Notion page",
        scope_label="Product workspace",
    ).model_dump(mode="json")
    data_source = NotionDataSourceReference(
        workspace_id="workspace-1",
        data_source_id="source-1",
        label="Projects",
        description="Notion data source",
        scope_label="Product workspace",
    ).model_dump(mode="json")
    created_page_id = str(uuid4())
    provider = AsyncMock()
    provider.get.return_value = {
        "object": "data_source",
        "id": "source-1",
        "in_trash": False,
        "title": [{"plain_text": "Projects"}],
        "properties": {
            "Name": {"type": "title", "title": {}},
            "Priority": {
                "type": "select",
                "select": {"options": [{"name": "High"}, {"name": "Low"}]},
            },
        },
    }
    provider.post.return_value = {
        "object": "page",
        "id": created_page_id,
        "url": f"https://www.notion.so/{created_page_id}",
        "last_edited_time": "2026-09-01T12:00:00.000Z",
        "in_trash": False,
        "properties": {},
    }
    monkeypatch.setattr(
        "integrations.notion.tools.create_page.notion_client",
        AsyncMock(return_value=provider),
    )

    async def run_targets(ctx, *, binding, references, operation):
        return await _run_authorized_entries(
            ctx,
            binding=binding,
            selected=((entry, references),),
            operation=operation,
        )

    monkeypatch.setattr(
        "integrations.notion.tools.create_page.run_context_targets",
        run_targets,
    )
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )
    authorize = AsyncMock(return_value=SimpleNamespace())
    resolve = AsyncMock(side_effect=lambda _authorized, *, values, **_kwargs: values)
    monkeypatch.setattr(
        "services.agents.runtime.entity_references.service.authorize_entity_field",
        authorize,
    )
    monkeypatch.setattr(
        "services.agents.runtime.entity_references.service.resolve_authorized_references",
        resolve,
    )
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[definition.name],
        tool_policies={definition.name: "approval"},
    )
    model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        definition.name,
                        {"title": "Draft launch", "parent_page": page},
                        "notion-create",
                    ),
                )
            ),
            "The approved Notion page was created.",
        ]
    )
    suspended = await run_scenario(db_session_factory, context, model=model)
    state = load_suspended_run_state(suspended.run)
    [pending] = state.deferred_tool_requests.approvals
    assert pending.args_as_dict()["title"] == "Draft launch"
    assert provider.mock_calls == []

    edited_args = {
        "title": "Approved launch",
        "parent_page": None,
        "parent_data_source": data_source,
        "content_md": "# Approved\n",
        "properties": [{"name": "Priority", "type": "select", "value": "High"}],
    }
    async with db_session_factory() as db:
        actor = await db.get(User, context.user_id)
        workspace = await db.get(Workspace, context.workspace_id)
        run = await db.get(AgentRun, context.run_id)
        membership = await db.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == context.workspace_id,
                WorkspaceMembership.user_id == context.user_id,
            )
        )
        assert actor is not None and workspace is not None and run is not None
        assert membership is not None
        deferred = await _build_deferred_tool_results(
            db,
            actor=actor,
            workspace=workspace,
            membership=membership,
            run=run,
            suspended_state=state,
            decisions=[
                AgentRunResumeDecision(
                    tool_call_id="notion-create",
                    decision="approved",
                    override_args=edited_args,
                )
            ],
        )

    completed = await run_scenario(
        db_session_factory,
        context,
        model=model,
        prompt=None,
        expected_status="awaiting_approval",
        message_history=state.message_history,
        deferred_tool_results=deferred,
    )

    assert completed.run.status == "completed"
    authorize.assert_awaited_once()
    assert authorize.await_args.kwargs["field_key"] == "parent_data_source"
    provider.post.assert_awaited_once()
    assert provider.post.await_args.kwargs["json"] == {
        "parent": {"type": "data_source_id", "data_source_id": "source-1"},
        "properties": {
            "Name": {"title": [{"type": "text", "text": {"content": "Approved launch"}}]},
            "Priority": {"select": {"name": "High"}},
        },
        "markdown": "# Approved\n",
    }
    assert [call.kwargs["status"] for call in audit.await_args_list] == [
        AuditStatus.PENDING,
        AuditStatus.SUCCESS,
    ]
    pending_detail = audit.await_args_list[0].kwargs["operation_detail"]
    assert pending_detail.intent_groups[0].items[0].fields == {
        "title": "Approved launch",
        "content_bytes": 11,
        "property_count": 1,
    }
    assert audit.await_args_list[1].kwargs["external_ref"] == created_page_id


async def test_code_mode_resume_reauthorizes_edits_and_rejects_changed_option_schema(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch,
) -> None:
    definition = replace(UPDATE_PROPERTIES_DEFINITION, availability_check=lambda: True)
    monkeypatch.setitem(RUNTIME_TOOL_CATALOG, definition.name, definition)
    _force_only_code_mode_tool(monkeypatch, definition)
    entry = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="notion",
        resource_type="notion_workspace",
        external_id="workspace-1",
        display_name="Product workspace",
        connection_id=uuid4(),
        connection_label="Product",
        connection_status="active",
        write_allowed=True,
    )
    page = NotionPageReference(
        workspace_id="workspace-1",
        page_id="page-1",
        label="Launch plan",
        description="Notion page",
        scope_label="Product workspace",
    ).model_dump(mode="json")
    live_options = ["Planned", "Done"]
    provider = AsyncMock()

    async def provider_get(path, **_kwargs):
        if path == "pages/page-1":
            return {
                "object": "page",
                "id": "page-1",
                "in_trash": False,
                "parent": {"type": "data_source_id", "data_source_id": "source-1"},
                "properties": {
                    "Name": {"type": "title", "title": [{"plain_text": "Launch plan"}]},
                    "Status": {"type": "status", "status": {"name": "Planned"}},
                    "Estimate": {"type": "number", "number": 3},
                },
            }
        return {
            "object": "data_source",
            "id": "source-1",
            "in_trash": False,
            "title": [{"plain_text": "Projects"}],
            "properties": {
                "Name": {"type": "title", "title": {}},
                "Status": {
                    "type": "status",
                    "status": {"options": [{"name": name} for name in live_options]},
                },
                "Estimate": {"type": "number", "number": {}},
            },
        }

    provider.get.side_effect = provider_get
    monkeypatch.setattr(
        "integrations.notion.tools.update_page_properties.notion_client",
        AsyncMock(return_value=provider),
    )

    async def run_targets(ctx, *, binding, references, operation):
        return await _run_authorized_entries(
            ctx,
            binding=binding,
            selected=((entry, references),),
            operation=operation,
        )

    monkeypatch.setattr(
        "integrations.notion.tools.update_page_properties.run_context_targets",
        run_targets,
    )
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )
    authorize = AsyncMock(return_value=SimpleNamespace())
    resolve = AsyncMock(side_effect=lambda _authorized, *, values, **_kwargs: values)
    monkeypatch.setattr(
        "services.agents.runtime.entity_references.service.authorize_entity_field",
        authorize,
    )
    monkeypatch.setattr(
        "services.agents.runtime.entity_references.service.resolve_authorized_references",
        resolve,
    )
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[definition.name],
        code_mode_enabled=True,
    )
    proposed = [{"name": "Status", "type": "status", "value": "Done"}]
    model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        RUN_WORKFLOW_TOOL_NAME,
                        {
                            "code": (
                                f"await notion_update_page_properties(page={page!r}, "
                                f"properties={proposed!r})"
                            )
                        },
                        "workflow-call",
                    ),
                )
            ),
            "The Notion change was blocked because its schema changed.",
        ]
    )
    suspended = await run_scenario(db_session_factory, context, model=model)
    state = load_suspended_run_state(suspended.run)
    live_options[:] = ["Planned"]
    edited = [
        *proposed,
        {"name": "Estimate", "type": "number", "value": "5"},
    ]

    async with db_session_factory() as db:
        actor = await db.get(User, context.user_id)
        workspace = await db.get(Workspace, context.workspace_id)
        run = await db.get(AgentRun, context.run_id)
        membership = await db.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == context.workspace_id,
                WorkspaceMembership.user_id == context.user_id,
            )
        )
        assert actor is not None and workspace is not None and run is not None
        assert membership is not None
        deferred = await _build_deferred_tool_results(
            db,
            actor=actor,
            workspace=workspace,
            membership=membership,
            run=run,
            suspended_state=state,
            decisions=[
                AgentRunResumeDecision(
                    tool_call_id="workflow-call:1",
                    decision="approved",
                    override_args={"page": page, "properties": edited},
                )
            ],
        )

    completed = await run_scenario(
        db_session_factory,
        context,
        model=model,
        prompt=None,
        expected_status="awaiting_approval",
        message_history=state.message_history,
        deferred_tool_results=deferred,
    )

    assert completed.run.status == "completed"
    authorize.assert_awaited_once()
    provider.patch.assert_not_awaited()
    assert [call.kwargs["status"] for call in audit.await_args_list] == [AuditStatus.FAILURE]
    nested = [row for row in completed.audit_rows if row.resource_id == "workflow-call:1"]
    assert sorted(row.status for row in nested) == ["pending", "success"]
    assert completed.output == "The Notion change was blocked because its schema changed."


def _force_only_code_mode_tool(monkeypatch, definition) -> None:
    from services.agents.runtime import loop

    original = loop.build_runtime_tools

    def forced_build(*args: Any, **kwargs: Any) -> list[Tool[Any]]:
        tools = original(*args, **kwargs)
        filtered = [
            tool for tool in tools if tool.name not in {definition.name, RUN_WORKFLOW_TOOL_NAME}
        ]
        catalog = CodeModeCatalog.build(((definition, "approval"),))
        return [*filtered, build_run_workflow_tool(catalog)]

    monkeypatch.setattr(loop, "build_runtime_tools", forced_build)


def _force_only_direct_tool(monkeypatch, definition) -> None:
    from services.agents.runtime import loop

    original = loop.build_runtime_tools

    def forced_build(*args: Any, **kwargs: Any) -> list[Tool[Any]]:
        tools = original(*args, **kwargs)
        filtered = [tool for tool in tools if tool.name != definition.name]
        return [*filtered, definition.to_pydantic_tool(policy="approval")]

    monkeypatch.setattr(loop, "build_runtime_tools", forced_build)
