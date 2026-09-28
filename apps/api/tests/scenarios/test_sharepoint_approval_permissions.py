"""SharePoint approval hydration enforces current write access before Graph I/O."""

from dataclasses import replace
from unittest.mock import AsyncMock

import httpx2
import pytest
from sqlalchemy import select

from core.exceptions.general import AppValidationError
from integrations.sharepoint.references import SharePointDriveItemReference
from integrations.sharepoint.tools.create_folder import DEFINITION as FOLDER_DEFINITION
from integrations.sharepoint.tools.update_file import DEFINITION as UPDATE_DEFINITION
from integrations.sharepoint.tools.write_file import DEFINITION as WRITE_DEFINITION
from models.agent_run import AgentRun
from models.audit_event import AuditEvent
from services.agents.runtime.code_mode.stubs import CodeModeCatalog
from services.agents.runtime.tools.code_mode import RUN_WORKFLOW_TOOL_NAME, build_run_workflow_tool
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.sharepoint.support import entry, file_metadata, fixture, graph
from tests.support.approvals import ScenarioDecision
from tests.support.delegation import resume_scenario
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)
from utils.quickxorhash import quickxorhash

DEFINITIONS = {
    "parent": FOLDER_DEFINITION,
    "folder": WRITE_DEFINITION,
    "file": UPDATE_DEFINITION,
}


def _arguments(field):
    reference = SharePointDriveItemReference(
        drive_id="drive",
        item_id="file" if field == "file" else "parent",
        kind="file" if field == "file" else "folder",
    ).model_dump(mode="json")
    if field == "parent":
        return {field: reference, "name": "New folder"}
    if field == "folder":
        return {field: reference, "name": "notes.txt", "content": "Text"}
    return {field: reference, "expected_version": '"version-1"', "content": "Text"}


def _configure(monkeypatch, db_session_factory, definition, active, *, nested):
    definition = replace(definition, availability_check=lambda: True)
    monkeypatch.setitem(RUNTIME_TOOL_CATALOG, definition.name, definition)
    monkeypatch.setattr(
        "services.agents.runtime.loop.build_runtime_tools",
        lambda *_args, **_kwargs: [
            build_run_workflow_tool(CodeModeCatalog.build(((definition, "approval"),)))
            if nested
            else definition.to_pydantic_tool(policy="approval")
        ],
    )
    for path in (
        "services.agents.runtime.execute.setup.resolve_active_context",
        "services.agents.runtime.entity_references.service.resolve_active_context",
    ):
        monkeypatch.setattr(path, active)
    monkeypatch.setattr(
        "services.audit_events.integration_events.get_async_db_session_factory",
        lambda: db_session_factory,
    )
    return definition


@pytest.mark.parametrize(
    ("nested", "field", "permission_lost"), [(False, "file", False), (True, "parent", True)]
)
async def test_resume_denies_before_real_entity_hydration(
    committed_db_session_factory, monkeypatch, nested, field, permission_lost
):
    db_session_factory = committed_db_session_factory
    selected = replace(entry(), write_allowed=permission_lost)
    active = AsyncMock(return_value=ResolvedActiveContext(entries=(selected,)))
    definition = _configure(
        monkeypatch, db_session_factory, DEFINITIONS[field], active, nested=nested
    )
    context = await build_scenario_agent(
        db_session_factory, tool_names=[definition.name], code_mode_enabled=nested
    )
    args = _arguments(field)
    code_args = ", ".join(f"{key}={value!r}" for key, value in args.items())
    call = (
        ToolCall(
            RUN_WORKFLOW_TOOL_NAME, {"code": f"await {definition.name}({code_args})"}, "workflow"
        )
        if nested
        else ToolCall(definition.name, args, "write")
    )
    model = scripted_model(turns=[ToolTurn((call,)), "The request finished."])
    requests = []

    def respond(request):
        requests.append(request)
        return httpx2.Response(200, json=file_metadata())

    async with graph(respond) as provider:
        credential_factory = AsyncMock(return_value=provider)
        monkeypatch.setattr(
            "integrations.sharepoint.entity_resolvers.drive_item.drive_client_for_principal",
            credential_factory,
        )
        monkeypatch.setattr(
            "integrations.sharepoint.tools.write_utils.drive_client", credential_factory
        )
        suspended = await run_scenario(db_session_factory, context, model=model)
        assert suspended.run.status == "awaiting_approval"
        active.return_value = ResolvedActiveContext(
            entries=(replace(selected, write_allowed=False),)
        )
        with pytest.raises(AppValidationError, match="does not permit writes") as caught:
            await resume_scenario(
                db_session_factory,
                context,
                model=model,
                decisions=[
                    ScenarioDecision(
                        tool_call_id="workflow:1" if nested else "write",
                        decision="approved",
                    )
                ],
            )
        assert caught.value.field == field
        assert caught.value.details["error_code"] == "write_not_permitted"
        credential_factory.assert_not_awaited()
        assert requests == []

    async with db_session_factory() as db:
        run = await db.get(AgentRun, context.run_id)
        assert run.status == "awaiting_approval"
        rows = list(
            await db.scalars(
                select(AuditEvent).where(AuditEvent.workspace_id == context.workspace_id)
            )
        )
    [denial] = [row for row in rows if row.details.get("provider_operation")]
    assert denial.status == "failure"
    assert denial.tool_name == definition.name
    assert denial.details["error_code"] == "write_not_permitted"
    assert denial.details["run_id"] == str(context.run_id)
    assert denial.details["tool_call_id"] == ("workflow:1" if nested else "write")
    assert denial.details["integration_resource_id"] == str(selected.integration_resource_id)
    assert denial.details["connection_id"] == str(selected.connection_id)
    assert denial.details["external_id"] == "drive"


@pytest.mark.parametrize(
    ("nested", "field", "changed_library"), [(False, "parent", False), (True, "folder", True)]
)
async def test_cleared_destination_resume_preserves_reviewed_root_binding(
    db_session_factory, monkeypatch, nested, field, changed_library
):
    selected = replace(entry(), write_allowed=True)
    active = AsyncMock(return_value=ResolvedActiveContext(entries=(selected,)))
    definition = _configure(
        monkeypatch, db_session_factory, DEFINITIONS[field], active, nested=nested
    )
    context = await build_scenario_agent(
        db_session_factory, tool_names=[definition.name], code_mode_enabled=nested
    )
    args = _arguments(field)
    code_args = ", ".join(f"{key}={value!r}" for key, value in args.items())
    call = (
        ToolCall(
            RUN_WORKFLOW_TOOL_NAME, {"code": f"await {definition.name}({code_args})"}, "workflow"
        )
        if nested
        else ToolCall(definition.name, args, "write")
    )
    model = scripted_model(turns=[ToolTurn((call,)), "The request finished."])
    suspended = await run_scenario(db_session_factory, context, model=model)
    assert suspended.run.status == "awaiting_approval"
    if changed_library:
        active.return_value = ResolvedActiveContext(
            entries=(replace(entry("other"), write_allowed=True),)
        )

    provider = AsyncMock()
    if field == "parent":
        provider.post.return_value = {
            **fixture("children.json")["value"][1],
            "id": "new-child",
            "name": args["name"],
            "eTag": '"version-2"',
            "parentReference": {"driveId": "drive", "path": "/drives/drive/root:"},
        }
    else:
        provider.post.return_value = {"uploadUrl": "https://example.sharepoint.com/upload"}
        provider.upload_fragment.return_value = file_metadata(
            id="new-child",
            eTag='"version-2"',
            size=4,
            parentReference={"driveId": "drive", "path": "/drives/drive/root:"},
            file={"mimeType": "text/plain", "hashes": {"quickXorHash": quickxorhash(b"Text")}},
        )
    credential_factory = AsyncMock(return_value=provider)
    resolver_factory = AsyncMock()
    monkeypatch.setattr(
        "integrations.sharepoint.tools.write_utils.drive_client", credential_factory
    )
    monkeypatch.setattr(
        "integrations.sharepoint.entity_resolvers.drive_item.drive_client_for_principal",
        resolver_factory,
    )
    completed = await resume_scenario(
        db_session_factory,
        context,
        model=model,
        decisions=[
            ScenarioDecision(
                tool_call_id="workflow:1" if nested else "write",
                decision="approved",
                override_args=args | {field: None},
            )
        ],
    )
    assert completed.run.status == "completed"
    resolver_factory.assert_not_awaited()
    operations = [row for row in completed.audit_rows if row.details.get("provider_operation")]
    if changed_library:
        assert [row.status for row in operations] == ["failure"]
        assert operations[0].details["error_code"] == "ModelRetry"
        assert "Prepare the action for approval again" in str(
            [message.parts for message in completed.messages]
        )
        credential_factory.assert_not_awaited()
        provider.post.assert_not_awaited()
        provider.upload_fragment.assert_not_awaited()
    else:
        assert sorted(row.status for row in operations) == ["pending", "success"]
        terminal = next(row for row in operations if row.status == "success")
        assert terminal.details["external_ref"] == "drive:new-child"
        assert provider.post.await_args.args[0].startswith("/drives/drive/root")
        provider.get.assert_not_awaited()
