# apps/api/tests/scenarios/test_sharepoint_file_write.py

"""SharePoint write consent and version checks through production resume."""

import json
from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from core.exceptions.integration import (
    IntegrationConnectionError,
    IntegrationFailureDisposition,
    IntegrationNotFoundError,
)
from integrations.sharepoint.references import SharePointDriveItemReference
from integrations.sharepoint.tools.create_folder import DEFINITION as FOLDER_DEFINITION
from integrations.sharepoint.tools.update_file import DEFINITION as UPDATE_DEFINITION
from integrations.sharepoint.tools.write_file import DEFINITION as WRITE_DEFINITION
from services.agent_runs.schemas import AgentRunResumeDecision
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.code_mode.stubs import CodeModeCatalog
from services.agents.runtime.tools.code_mode import RUN_WORKFLOW_TOOL_NAME, build_run_workflow_tool
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.sharepoint.support import entry, file_metadata, fixture
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
    "create_folder": FOLDER_DEFINITION,
    "write_file": WRITE_DEFINITION,
    "update_file": UPDATE_DEFINITION,
}
UPLOAD_URL = "https://example.sharepoint.com/upload?token=PRIVATE_UPLOAD_SECRET"
APPROVED_CONTENT = "Approved document text."


def _arguments(action):
    if action == "create_folder":
        return {"name": "Proposed folder"}
    if action == "write_file":
        return {"name": "notes.txt", "content": "Proposed document text."}
    return {
        "file": SharePointDriveItemReference(
            drive_id="drive", item_id="file", kind="file"
        ).model_dump(mode="json"),
        "expected_version": '"version-1"',
        "content": "Proposed document text.",
    }


def _provider(action):
    provider = AsyncMock()
    provider.get.return_value = file_metadata()
    if action == "create_folder":
        provider.post.return_value = {
            **fixture("children.json")["value"][1],
            "name": "Approved folder",
            "eTag": '"version-2"',
        }
    else:
        provider.post.return_value = {"uploadUrl": UPLOAD_URL}
        provider.upload_fragment.return_value = file_metadata(
            eTag='"version-2"',
            size=len(APPROVED_CONTENT.encode()),
            file={
                "mimeType": "text/plain",
                "hashes": {"quickXorHash": quickxorhash(APPROVED_CONTENT.encode())},
            },
        )
    return provider


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize(
    ("action", "outcome"),
    [
        ("create_folder", "applied"),
        ("create_folder", "denied"),
        ("write_file", "applied"),
        ("write_file", "denied"),
        ("update_file", "applied"),
        ("update_file", "denied"),
        ("update_file", "version_conflict"),
        ("create_folder", "library_changed"),
        ("write_file", "library_changed"),
        ("create_folder", "connection_changed"),
        ("write_file", "connection_changed"),
        ("update_file", "connection_changed"),
        ("create_folder", "resource_changed"),
        ("write_file", "resource_changed"),
        ("update_file", "resource_changed"),
        ("create_folder", "edited_destination"),
        ("write_file", "edited_destination"),
        ("write_file", "incomplete"),
        ("update_file", "incomplete"),
        ("write_file", "missing"),
        ("update_file", "missing"),
        ("write_file", "unavailable"),
        ("update_file", "unavailable"),
        ("update_file", "unchanged_version"),
    ],
)
async def test_sharepoint_write_approval_resume(
    db_session_factory, monkeypatch, nested, action, outcome
):
    definition = replace(DEFINITIONS[action], availability_check=lambda: True)
    monkeypatch.setitem(RUNTIME_TOOL_CATALOG, definition.name, definition)
    monkeypatch.setattr(
        "services.agents.runtime.loop.build_runtime_tools",
        lambda *_args, **_kwargs: [
            build_run_workflow_tool(CodeModeCatalog.build(((definition, "approval"),)))
            if nested
            else definition.to_pydantic_tool(policy="approval")
        ],
    )
    selected = replace(entry(), write_allowed=True)
    active_context = AsyncMock(return_value=ResolvedActiveContext(entries=(selected,)))
    monkeypatch.setattr(
        "services.agents.runtime.execute.setup.resolve_active_context",
        active_context,
    )
    monkeypatch.setattr(
        "services.audit_events.integration_events.get_async_db_session_factory",
        lambda: db_session_factory,
    )
    monkeypatch.setattr(
        "services.agents.runtime.entity_references.service.authorize_entity_field", AsyncMock()
    )
    monkeypatch.setattr(
        "services.agents.runtime.entity_references.service.resolve_authorized_references",
        AsyncMock(side_effect=lambda _authorised, *, values, **_kwargs: values),
    )
    provider = _provider(action)
    monkeypatch.setattr(
        "integrations.sharepoint.tools.write_utils.drive_client", AsyncMock(return_value=provider)
    )
    args = _arguments(action)
    code_args = ", ".join(f"{key}={value!r}" for key, value in args.items())
    context = await build_scenario_agent(
        db_session_factory, tool_names=[definition.name], code_mode_enabled=nested
    )
    call = (
        ToolCall(
            RUN_WORKFLOW_TOOL_NAME,
            {"code": f"await {definition.name}({code_args})"},
            "workflow",
        )
        if nested
        else ToolCall(definition.name, args, "write")
    )
    model = scripted_model(turns=[ToolTurn((call,)), "The SharePoint request finished."])
    suspended = await run_scenario(db_session_factory, context, model=model)
    assert suspended.run.status == "awaiting_approval"
    assert provider.mock_calls == []
    state = load_suspended_run_state(suspended.run)
    display = state.deferred_tool_requests.metadata[call.call_id]["display_args"]
    assert display["_library"] == "Documents"
    assert display["_target"] == {
        "drive_id": selected.external_id,
        "resource_id": str(selected.integration_resource_id),
        "connection_id": str(selected.connection_id),
    }
    for key, value in args.items():
        assert display[key] == value

    edited = args | (
        {"name": "Approved folder"} if action == "create_folder" else {"content": APPROVED_CONTENT}
    )
    if outcome == "version_conflict":
        provider.get.return_value = file_metadata(eTag='"changed-after-approval"')
    unverified = outcome in {"incomplete", "missing", "unavailable", "unchanged_version"}
    if unverified:
        saved = dict(provider.upload_fragment.return_value)
        if outcome == "unchanged_version":
            saved["eTag"] = '"version-1"'
        provider.get.side_effect = (
            [file_metadata(), file_metadata(), saved] if action == "update_file" else [saved]
        )
        provider.upload_fragment.side_effect = IntegrationConnectionError(
            "The upload response was lost.",
            failure_disposition=IntegrationFailureDisposition.AMBIGUOUS,
            error_code="upload_interrupted",
        )
        if outcome in {"missing", "unchanged_version"}:
            provider.upload_status.side_effect = IntegrationNotFoundError(
                "The session is unavailable.", error_code="upload_session_expired"
            )
        elif outcome == "unavailable":
            provider.upload_status.side_effect = IntegrationConnectionError("Status unavailable.")
        else:
            provider.upload_status.return_value = {"nextExpectedRanges": ["0-"]}
    if outcome in {"library_changed", "edited_destination"}:
        active_context.return_value = ResolvedActiveContext(
            entries=(replace(selected, external_id="other"),)
        )
    if outcome == "connection_changed":
        active_context.return_value = ResolvedActiveContext(
            entries=(replace(selected, connection_id=uuid4()),)
        )
    if outcome == "resource_changed":
        active_context.return_value = ResolvedActiveContext(
            entries=(replace(selected, integration_resource_id=uuid4()),)
        )
    if outcome == "edited_destination":
        edited["parent" if action == "create_folder" else "folder"] = SharePointDriveItemReference(
            drive_id="other", item_id="approved-parent", kind="folder"
        ).model_dump(mode="json")
        folder = fixture("children.json")["value"][1]
        folder["id"] = "approved-parent"
        folder["parentReference"]["driveId"] = "other"
        provider.get.return_value = folder
        saved = provider.post if action == "create_folder" else provider.upload_fragment
        saved.return_value["parentReference"] = {"driveId": "other", "id": "approved-parent"}
    completed = await resume_scenario(
        db_session_factory,
        context,
        model=model,
        decisions=[
            AgentRunResumeDecision(
                tool_call_id="workflow:1" if nested else "write",
                decision="denied" if outcome == "denied" else "approved",
                override_args=None if outcome == "denied" else edited,
            )
        ],
    )
    assert completed.run.status == "completed"
    operations = [row for row in completed.audit_rows if row.details.get("provider_operation")]
    if outcome in {"library_changed", "connection_changed", "resource_changed"}:
        assert provider.mock_calls == []
        assert [row.status for row in operations] == ["failure"]
        assert "changed after review" in str([row.parts for row in completed.messages])
        return
    if outcome == "denied":
        assert provider.mock_calls == []
        assert operations == []
        assert any(row.status == "denied" for row in completed.audit_rows)
        return
    if outcome == "version_conflict":
        provider.post.assert_not_awaited()
        provider.upload_fragment.assert_not_awaited()
        assert [row.status for row in operations] == ["failure"]
        assert operations[0].details["error_code"] == "version_conflict"
        return

    if unverified:
        assert sorted(row.status for row in operations) == ["pending", "unverified"]
        pending = next(row for row in operations if row.status == "pending")
        terminal = next(row for row in operations if row.status == "unverified")
        assert terminal.details["related_event_id"] == str(pending.id)
        detail = terminal.details["operation_detail"]
        effect = detail["outcome_groups"][0]["outcomes"][0]["effects"][0]
        assert effect["status"] == "unverified"
        assert effect["error_code"] == "unverified_mutation"
        assert effect["fields"]["committed"] is False
        assert effect["fields"]["hash_matched"] is True
        assert effect["fields"]["session_status"] == (
            "missing" if outcome == "unchanged_version" else outcome
        )
        assert effect["fields"]["bytes_sent"] == 0
        provider.post.assert_awaited_once()
        provider.upload_fragment.assert_awaited_once()
        provider.upload_status.assert_awaited_once()
        provider.cancel_upload.assert_not_awaited()
        assert provider.get.await_count == (3 if action == "update_file" else 1)
        transcript = str([row.parts for row in completed.messages])
        assert "unverified_mutation" in transcript
        assert "PRIVATE_UPLOAD_SECRET" not in transcript
        assert "PRIVATE_UPLOAD_SECRET" not in json.dumps(
            [row.details for row in operations], default=str
        )
        return

    assert sorted(row.status for row in operations) == ["pending", "success"]
    pending = next(row for row in operations if row.status == "pending")
    terminal = next(row for row in operations if row.status == "success")
    assert terminal.details["related_event_id"] == str(pending.id)
    item_id = "folder" if action == "create_folder" else "file"
    drive_id = "other" if outcome == "edited_destination" else "drive"
    assert terminal.details["external_ref"] == f"{drive_id}:{item_id}"
    assert provider.post.await_args.args[0].startswith(f"/drives/{drive_id}/")
    if outcome == "edited_destination":
        parent_path = (
            "approved-parent/children"
            if action == "create_folder"
            else "approved-parent:/notes.txt:/createUploadSession"
        )
        assert provider.post.await_args.args[0] == f"/drives/other/items/{parent_path}"
        saved = provider.post if action == "create_folder" else provider.upload_fragment
        assert saved.return_value["parentReference"]["id"] == "approved-parent"
        assert saved.return_value["id"] != "approved-parent"
    if action == "create_folder":
        assert provider.post.await_args.kwargs["json"]["name"] == "Approved folder"
        provider.upload_fragment.assert_not_awaited()
    else:
        assert provider.upload_fragment.await_args.args[1] == APPROVED_CONTENT.encode()
        if action == "update_file":
            assert provider.post.await_args.kwargs["headers"] == {"If-Match": '"version-1"'}
    effect = terminal.details["operation_detail"]["outcome_groups"][0]["outcomes"][0]["effects"][0]
    assert effect["fields"]["etag_after"] == '"version-2"'
    if action == "update_file":
        assert effect["fields"]["etag_before"] == '"version-1"'
    evidence = json.dumps([row.details for row in operations], default=str)
    assert "PRIVATE_UPLOAD_SECRET" not in evidence
    assert "PRIVATE_DOWNLOAD_SECRET" not in evidence
    assert APPROVED_CONTENT not in json.dumps(pending.details, default=str)
    assert "Approved folder" not in json.dumps(pending.details, default=str)
