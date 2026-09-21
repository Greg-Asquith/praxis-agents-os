"""SharePoint approval hydration enforces current write access before Graph I/O."""

from dataclasses import replace
from unittest.mock import AsyncMock

import httpx2
import pytest
from sqlalchemy import select

from core.exceptions.general import AppValidationError
from integrations.sharepoint.references import SharePointDriveItemReference
from integrations.sharepoint.tools.create_folder import DEFINITION as FOLDER_DEFINITION
from integrations.sharepoint.tools.list_folder import DEFINITION as LIST_DEFINITION
from integrations.sharepoint.tools.update_file import DEFINITION as UPDATE_DEFINITION
from integrations.sharepoint.tools.write_file import DEFINITION as WRITE_DEFINITION
from models.agent_run import AgentRun
from models.audit_event import AuditEvent
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.agent_runs.schemas import AgentRunResumeDecision
from services.agents.runtime.code_mode.stubs import CodeModeCatalog
from services.agents.runtime.entity_references.schemas import EntityReferenceLookupRequest
from services.agents.runtime.entity_references.service import lookup_entity_references
from services.agents.runtime.tools.code_mode import RUN_WORKFLOW_TOOL_NAME, build_run_workflow_tool
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.sharepoint.support import entry, file_metadata, fixture, graph
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


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("field", ["file", "folder", "parent"])
@pytest.mark.parametrize("permission_lost", [False, True])
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
                    AgentRunResumeDecision(
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


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("field", ["folder", "parent"])
async def test_writable_destination_edit_uses_real_canonical_resolution(
    db_session_factory, monkeypatch, nested, field
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
    args.pop(field)
    code_args = ", ".join(f"{key}={value!r}" for key, value in args.items())
    call = (
        ToolCall(
            RUN_WORKFLOW_TOOL_NAME, {"code": f"await {definition.name}({code_args})"}, "workflow"
        )
        if nested
        else ToolCall(definition.name, args, "write")
    )
    model = scripted_model(turns=[ToolTurn((call,)), "The file was saved."])
    suspended = await run_scenario(db_session_factory, context, model=model)
    assert suspended.run.status == "awaiting_approval"
    destination = replace(entry("other"), write_allowed=True, display_name="Other library")
    active.return_value = ResolvedActiveContext(entries=(destination,))
    parent = {
        **fixture("children.json")["value"][1],
        "id": "approved-parent",
        "name": "Fresh destination",
        "parentReference": {"driveId": "other"},
    }
    provider = AsyncMock()
    provider.get.return_value = parent
    if field == "parent":
        provider.post.return_value = {
            **parent,
            "id": "new-child",
            "name": args["name"],
            "eTag": '"version-2"',
            "parentReference": {"driveId": "other", "id": "approved-parent"},
        }
    else:
        provider.post.return_value = {"uploadUrl": "https://example.sharepoint.com/upload"}
        provider.upload_fragment.return_value = file_metadata(
            id="new-child",
            eTag='"version-2"',
            size=4,
            parentReference={"driveId": "other", "id": "approved-parent"},
            file={"mimeType": "text/plain", "hashes": {"quickXorHash": quickxorhash(b"Text")}},
        )
    monkeypatch.setattr(
        "integrations.sharepoint.tools.write_utils.drive_client", AsyncMock(return_value=provider)
    )
    edited = args | {
        field: SharePointDriveItemReference(
            drive_id="other", item_id="approved-parent", kind="folder", label="Stale label"
        ).model_dump(mode="json")
    }
    requests = []

    def respond(request):
        requests.append(request.url.path)
        return httpx2.Response(200, json=parent)

    async with graph(respond) as resolver_client:
        monkeypatch.setattr(
            "integrations.sharepoint.entity_resolvers.drive_item.drive_client_for_principal",
            AsyncMock(return_value=resolver_client),
        )
        completed = await resume_scenario(
            db_session_factory,
            context,
            model=model,
            decisions=[
                AgentRunResumeDecision(
                    tool_call_id="workflow:1" if nested else "write",
                    decision="approved",
                    override_args=edited,
                )
            ],
        )
    assert requests == ["/v1.0/drives/other/items/approved-parent"]
    assert completed.run.status == "completed"
    operations = [row for row in completed.audit_rows if row.details.get("provider_operation")]
    assert sorted(row.status for row in operations) == ["pending", "success"]
    terminal = next(row for row in operations if row.status == "success")
    assert terminal.details["external_ref"] == "other:new-child"
    assert provider.post.await_args.args[0].startswith("/drives/other/items/approved-parent")
    saved = provider.post if field == "parent" else provider.upload_fragment
    assert saved.return_value["parentReference"] == {"driveId": "other", "id": "approved-parent"}


@pytest.mark.parametrize("write", [False, True])
@pytest.mark.parametrize("exact", [False, True])
@pytest.mark.parametrize("ambiguous", [False, True])
async def test_authorized_lookup_preserves_reads_and_filters_write_choices(
    db_session_factory, monkeypatch, write, exact, ambiguous
):
    readonly = entry()
    writable = replace(entry("drive" if ambiguous else "writable"), write_allowed=True)
    active = AsyncMock(return_value=ResolvedActiveContext(entries=(readonly, writable)))
    definition = _configure(
        monkeypatch,
        db_session_factory,
        WRITE_DEFINITION if write else LIST_DEFINITION,
        active,
        nested=False,
    )
    context = await build_scenario_agent(db_session_factory, tool_names=[definition.name])
    requests = []

    def respond(request):
        requests.append(request.url.path)
        drive = "writable" if "/writable/" in request.url.path else "drive"
        item = {**fixture("children.json")["value"][1], "parentReference": {"driveId": drive}}
        return httpx2.Response(200, json=item if exact else {"value": [item]})

    async with graph(respond) as provider, db_session_factory() as db:
        credential_factory = AsyncMock(return_value=provider)
        monkeypatch.setattr(
            "integrations.sharepoint.entity_resolvers.drive_item.drive_client_for_principal",
            credential_factory,
        )
        actor = await db.get(User, context.user_id)
        workspace = await db.get(Workspace, context.workspace_id)
        membership = await db.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == context.workspace_id,
                WorkspaceMembership.user_id == context.user_id,
            )
        )
        payload = EntityReferenceLookupRequest(
            tool_name=definition.name,
            field_key="folder",
            exact_values=[
                SharePointDriveItemReference(
                    drive_id="drive", item_id="folder", kind="folder"
                ).model_dump(mode="json")
            ]
            if exact
            else None,
        )
        if write and exact and not ambiguous:
            with pytest.raises(AppValidationError, match="does not permit writes"):
                await lookup_entity_references(
                    db,
                    actor=actor,
                    workspace=workspace,
                    membership=membership,
                    conversation_id=context.conversation_id,
                    payload=payload,
                )
            credential_factory.assert_not_awaited()
            assert requests == []
        else:
            result = await lookup_entity_references(
                db,
                actor=actor,
                workspace=workspace,
                membership=membership,
                conversation_id=context.conversation_id,
                payload=payload,
            )
            expected = {"writable"} if write else {"drive"} if exact else {"drive", "writable"}
            if ambiguous:
                expected = set()
            assert {choice.value["drive_id"] for choice in result.choices} == expected
            assert len(requests) == credential_factory.await_count == len(expected)
