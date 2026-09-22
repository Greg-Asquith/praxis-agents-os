"""Copy and replace workbook revisions through direct and Code Mode approval."""

import importlib
import json
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID, uuid4
from zipfile import ZipFile

import pytest
from sqlalchemy import select

from core.database import maintenance_async_db_session
from core.exceptions.general import AppValidationError
from core.exceptions.integration import (
    IntegrationConnectionError,
    IntegrationFailureDisposition,
    IntegrationNotFoundError,
)
from core.settings import settings
from integrations.sharepoint.references import SharePointDriveItemReference
from integrations.sharepoint.tools.copy_to_files import DEFINITION as COPY_DEFINITION
from integrations.sharepoint.tools.update_file import DEFINITION as UPDATE_DEFINITION
from integrations.sharepoint.tools.write_file import DEFINITION as WRITE_DEFINITION
from models.agent_run import AgentRun
from models.files import File, FileFolder, FileReference, FileRevision
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.agent_runs.schemas import AgentRunResumeDecision
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.code_mode.stubs import CodeModeCatalog
from services.agents.runtime.entity_references.domain import FileReference as SourceReference
from services.agents.runtime.tools.code_mode import RUN_WORKFLOW_TOOL_NAME, build_run_workflow_tool
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.files.append_file_revision import append_file_revision
from services.files.revision_actor import FileRevisionActor
from services.files.utils import file_revision_ref, sha256_hex
from services.integrations.context.domain import ResolvedActiveContext
from services.storage.factory import get_storage_provider
from tests.factories import build_file, build_file_revision, build_workspace
from tests.integrations.sharepoint.support import entry, file_metadata
from tests.support.approvals import compile_scenario_decisions
from tests.support.delegation import resume_scenario
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    next_scenario_run,
    run_scenario,
    scripted_model,
)
from tests.support.storage import reset_storage_provider_cache
from utils.content import ContentScope
from utils.quickxorhash import quickxorhash

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
WORKBOOK = Path(__file__).parents[1] / "integrations/sharepoint/fixtures/sheet.xlsx"
UPLOAD_URL = "https://example.sharepoint.com/upload?token=PRIVATE_UPLOAD_SECRET"


@pytest.fixture
def document_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    reset_storage_provider_cache()
    try:
        yield
    finally:
        reset_storage_provider_cache()


def _edited_workbook():
    output = BytesIO()
    with ZipFile(WORKBOOK) as original, ZipFile(output, "w") as edited:
        for member in original.infolist():
            content = original.read(member.filename)
            if member.filename == "xl/worksheets/sheet1.xml":
                assert b"2230" in content
                content = content.replace(b"2230", b"3000")
            edited.writestr(member, content)
    return output.getvalue()


def _call(definition, args, *, nested, call_id):
    if nested:
        return ToolCall(
            RUN_WORKFLOW_TOOL_NAME,
            {"code": f"await {definition.name}(**{args!r})"},
            call_id,
        )
    return ToolCall(definition.name, args, call_id)


def _copy_result(result, call, *, nested):
    [returned] = result.tool_returns(call.name)
    payload = (
        returned["metadata"]["code_mode_trace"]["calls"][0]["presentation_result"]
        if nested
        else returned["content"]
    )
    return payload["results"][0]["data"]


async def _append_revision(session_factory, context, file_id, content):
    async with session_factory() as db:
        workspace = await db.get(Workspace, context.workspace_id)
        result = await append_file_revision(
            db,
            workspace=workspace,
            file_id=file_id,
            content=content,
            actor=FileRevisionActor(agent_id=context.agent_id),
        )
        await db.commit()
        return result.revision.id


def _configure_runtime(
    monkeypatch, db_session_factory, definitions, *, nested, real_entities=False
):
    for definition, _policy in definitions:
        monkeypatch.setitem(RUNTIME_TOOL_CATALOG, definition.name, definition)
    monkeypatch.setattr(
        "services.agents.runtime.loop.build_runtime_tools",
        lambda *_args, **_kwargs: (
            [build_run_workflow_tool(CodeModeCatalog.build(definitions))]
            if nested
            else [definition.to_pydantic_tool(policy=policy) for definition, policy in definitions]
        ),
    )
    selected = replace(entry(), write_allowed=True)
    active = AsyncMock(return_value=ResolvedActiveContext(entries=(selected,)))
    monkeypatch.setattr("services.agents.runtime.execute.setup.resolve_active_context", active)
    monkeypatch.setattr(
        "services.agents.runtime.entity_references.service.resolve_active_context", active
    )
    monkeypatch.setattr(
        "services.audit_events.integration_events.get_async_db_session_factory",
        lambda: db_session_factory,
    )
    if not real_entities:
        monkeypatch.setattr(
            "services.agents.runtime.entity_references.service.authorize_entity_field", AsyncMock()
        )
        monkeypatch.setattr(
            "services.agents.runtime.entity_references.service.resolve_authorized_references",
            AsyncMock(side_effect=lambda _authorised, *, values, **_kwargs: values),
        )
    return active, selected


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("outcome", ["applied", "version_conflict", "source_changed", "unverified"])
async def test_sharepoint_document_loop(
    db_session_factory, monkeypatch, document_storage, nested, outcome
):
    copy = replace(COPY_DEFINITION, availability_check=lambda: True)
    update = replace(UPDATE_DEFINITION, availability_check=lambda: True)
    active, selected = _configure_runtime(
        monkeypatch, db_session_factory, ((copy, "auto"), (update, "approval")), nested=nested
    )
    original = WORKBOOK.read_bytes()
    edited = _edited_workbook()
    provider = AsyncMock()
    before = file_metadata(name="sheet.xlsx", size=len(original), file={"mimeType": XLSX})
    provider.get.return_value = before
    provider.get_bytes.return_value = original
    provider.post.return_value = {"uploadUrl": UPLOAD_URL}
    saved = file_metadata(
        name="sheet.xlsx",
        eTag='"version-2"',
        size=len(edited),
        file={"mimeType": XLSX, "hashes": {"quickXorHash": quickxorhash(edited)}},
    )
    provider.upload_fragment.return_value = saved
    for module in ("copy_to_files", "write_utils"):
        monkeypatch.setattr(
            f"integrations.sharepoint.tools.{module}.drive_client", AsyncMock(return_value=provider)
        )
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[copy.name, update.name],
        tool_policies={copy.name: "auto", update.name: "approval"},
        code_mode_enabled=nested,
    )
    remote = SharePointDriveItemReference(drive_id="drive", item_id="file", kind="file").model_dump(
        mode="json"
    )
    copy_call = _call(
        copy, {"file": remote, "folder": "SharePoint copies"}, nested=nested, call_id="copy"
    )
    copied = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(turns=[ToolTurn((copy_call,)), "The workbook was copied."]),
    )
    assert copied.run.status == "completed"
    data = _copy_result(copied, copy_call, nested=nested)
    assert data["version"] == '"version-1"'
    file_id = UUID(data["file_id"])
    original_revision_id = UUID(data["revision_id"])
    async with db_session_factory() as db:
        file = await db.get(File, file_id)
        folder = await db.get(FileFolder, file.folder_id)
        assert folder.name == "SharePoint copies"
        assert folder.workspace_id == context.workspace_id
        link = await db.scalar(
            select(FileReference).where(
                FileReference.workspace_id == context.workspace_id,
                FileReference.file_id == file_id,
                FileReference.target_type == "conversation",
                FileReference.target_id == context.conversation_id,
            )
        )
        assert link is not None
        original_revision = await db.get(FileRevision, original_revision_id)
        assert original_revision.created_by_agent_id == context.agent_id
        assert (
            await get_storage_provider().get_object(file_revision_ref(original_revision))
            == original
        )
    edited_revision_id = await _append_revision(db_session_factory, context, file_id, edited)
    assert edited_revision_id != original_revision_id
    provider.reset_mock()

    context = await next_scenario_run(db_session_factory, context)
    args = {
        "file": remote,
        "expected_version": data["version"],
        "source": data["reference"],
    }
    update_call = _call(update, args, nested=nested, call_id="replace")
    model = scripted_model(turns=[ToolTurn((update_call,)), "The replacement request finished."])
    suspended = await run_scenario(db_session_factory, context, model=model)
    assert suspended.run.status == "awaiting_approval"
    state = load_suspended_run_state(suspended.run)
    display = state.deferred_tool_requests.metadata[update_call.call_id]["display_args"]
    assert display["_source"]["file_id"] == str(file_id)
    assert display["_source"]["revision_id"] == str(edited_revision_id)
    assert display["_source"]["content_type"] == XLSX
    assert display["_source"]["size_bytes"] == len(edited)
    provider.post.assert_not_awaited()
    provider.upload_fragment.assert_not_awaited()

    if outcome == "version_conflict":
        provider.get.return_value = before | {"eTag": '"concurrent-remote-edit"'}
    elif outcome == "source_changed":

        async def change_after_approval(*_args, **_kwargs):
            await _append_revision(db_session_factory, context, file_id, original)
            return ResolvedActiveContext(entries=(selected,))

        active.side_effect = change_after_approval
    elif outcome == "unverified":
        provider.get.side_effect = [before, before, saved]
        provider.upload_fragment.side_effect = IntegrationConnectionError(
            "The upload response was lost.",
            failure_disposition=IntegrationFailureDisposition.AMBIGUOUS,
            error_code="upload_interrupted",
        )
        provider.upload_status.side_effect = IntegrationNotFoundError(
            "The session is unavailable.", error_code="upload_session_expired"
        )

    completed = await resume_scenario(
        db_session_factory,
        context,
        model=model,
        decisions=[
            AgentRunResumeDecision(
                tool_call_id="replace:1" if nested else "replace", decision="approved"
            )
        ],
    )
    assert completed.run.status == "completed"
    operations = [
        row
        for row in completed.audit_rows
        if row.details.get("provider_operation") == "update_file"
    ]
    evidence = json.dumps([row.parts for row in completed.messages], default=str)
    evidence += json.dumps([row.details for row in operations], default=str)
    assert "PRIVATE_UPLOAD_SECRET" not in evidence
    assert "PRIVATE_DOWNLOAD_SECRET" not in evidence
    if outcome in {"version_conflict", "source_changed"}:
        provider.post.assert_not_awaited()
        provider.upload_fragment.assert_not_awaited()
        assert [row.status for row in operations] == ["failure"]
        assert operations[0].details["error_code"] == outcome
        assert outcome in evidence
    else:
        terminal_status = "success" if outcome == "applied" else "unverified"
        assert sorted(row.status for row in operations) == ["pending", terminal_status]
        pending = next(row for row in operations if row.status == "pending")
        terminal = next(row for row in operations if row.status == terminal_status)
        assert terminal.details["related_event_id"] == str(pending.id)
        effect = terminal.details["operation_detail"]["outcome_groups"][0]["outcomes"][0][
            "effects"
        ][0]
        assert effect["fields"]["hash_matched"] is True
        assert effect["fields"]["committed"] is (outcome == "applied")
        assert effect["fields"]["etag_before"] == '"version-1"'
        assert effect["fields"]["etag_after"] == '"version-2"'
        provider.upload_fragment.assert_awaited_once()
        assert provider.upload_fragment.await_args.args[1] == edited
        assert provider.post.await_args.kwargs["headers"] == {"If-Match": '"version-1"'}
        if outcome == "unverified":
            assert effect["error_code"] == "unverified_mutation"
            assert effect["fields"]["session_status"] == "missing"
            provider.upload_status.assert_awaited_once()
            provider.cancel_upload.assert_not_awaited()
    async with db_session_factory() as db:
        file = await db.get(File, file_id)
        original_revision = await db.get(FileRevision, original_revision_id)
        edited_revision = await db.get(FileRevision, edited_revision_id)
        assert file.revision_count == (3 if outcome == "source_changed" else 2)
        assert (
            await get_storage_provider().get_object(file_revision_ref(original_revision))
            == original
        )
        assert await get_storage_provider().get_object(file_revision_ref(edited_revision)) == edited


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("decision", ["approved", "denied"])
async def test_copy_to_files_respects_approval_policy(
    db_session_factory, monkeypatch, document_storage, nested, decision
):
    definition = replace(COPY_DEFINITION, availability_check=lambda: True)
    _configure_runtime(monkeypatch, db_session_factory, ((definition, "approval"),), nested=nested)
    provider = AsyncMock()
    original = WORKBOOK.read_bytes()
    provider.get.return_value = file_metadata(
        name="sheet.xlsx", size=len(original), file={"mimeType": XLSX}
    )
    provider.get_bytes.return_value = original
    monkeypatch.setattr(
        "integrations.sharepoint.tools.copy_to_files.drive_client", AsyncMock(return_value=provider)
    )
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[definition.name],
        tool_policies={definition.name: "approval"},
        code_mode_enabled=nested,
    )
    remote = SharePointDriveItemReference(drive_id="drive", item_id="file", kind="file").model_dump(
        mode="json"
    )
    call = _call(definition, {"file": remote}, nested=nested, call_id="copy")
    model = scripted_model(turns=[ToolTurn((call,)), "The copy request finished."])
    suspended = await run_scenario(db_session_factory, context, model=model)
    assert suspended.run.status == "awaiting_approval"
    assert provider.mock_calls == []
    completed = await resume_scenario(
        db_session_factory,
        context,
        model=model,
        decisions=[
            AgentRunResumeDecision(tool_call_id="copy:1" if nested else "copy", decision=decision)
        ],
    )
    assert completed.run.status == "completed"
    async with db_session_factory() as db:
        files = (
            await db.scalars(select(File).where(File.workspace_id == context.workspace_id))
        ).all()
    if decision == "denied":
        assert provider.mock_calls == []
        assert files == []
        assert any(row.status == "denied" for row in completed.audit_rows)
    else:
        assert len(files) == 1
        provider.get_bytes.assert_awaited_once()
        assert any(
            row.status == "success" and row.details.get("provider_operation") == "copy_to_files"
            for row in completed.audit_rows
        )


async def _source_file(context, content, *, visibility="workspace"):
    async with maintenance_async_db_session() as db:
        workspace = await db.get(Workspace, context.workspace_id)
        if visibility == "foreign":
            workspace = build_workspace(slug=f"foreign-source-{uuid4().hex[:8]}")
            db.add(workspace)
            await db.flush()
        file = build_file(
            workspace=workspace,
            name="reviewed.xlsx",
            content_type=XLSX,
            extension=".xlsx",
            size_bytes=len(content),
            content_hash=sha256_hex(content),
            deleted=visibility == "deleted",
            **(
                {"scope": ContentScope.PLATFORM, "workspace_id": None}
                if visibility == "platform"
                else {}
            ),
        )
        db.add(file)
        await db.flush()
        revision = build_file_revision(file, is_published=visibility == "platform")
        db.add(revision)
        await db.flush()
        file.current_revision_id = revision.id
        file.revision_count = 1
        if visibility == "platform":
            file.published_revision_id = revision.id
            file.is_published = True
        await get_storage_provider().put_object(
            file_revision_ref(revision), content, content_type=XLSX
        )
        return file, revision


async def _compile_source_decision(session_factory, context, decision):
    async with session_factory() as db:
        return await compile_scenario_decisions(
            db,
            actor=await db.get(User, context.user_id),
            workspace=await db.get(Workspace, context.workspace_id),
            membership=await db.scalar(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == context.workspace_id,
                    WorkspaceMembership.user_id == context.user_id,
                )
            ),
            run=await db.get(AgentRun, context.run_id),
            decisions=[decision],
        )


@pytest.mark.parametrize("nested", [False, True], ids=["direct", "code_mode"])
@pytest.mark.parametrize("outcome", ["applied", "source_changed", "deleted", "substituted"])
async def test_file_source_approval_uses_real_core_authorisation(
    db_session_factory, monkeypatch, document_storage, nested, outcome
):
    definition = replace(WRITE_DEFINITION, availability_check=lambda: True)
    _configure_runtime(
        monkeypatch,
        db_session_factory,
        ((definition, "approval"),),
        nested=nested,
        real_entities=True,
    )
    context = await build_scenario_agent(
        db_session_factory, tool_names=[definition.name], code_mode_enabled=nested
    )
    content = WORKBOOK.read_bytes()
    file, revision = await _source_file(context, content)
    args = {
        "name": "saved.xlsx",
        "source": SourceReference(
            entity_id=file.id, label="Untrusted source label", description="Untrusted description"
        ).model_dump(mode="json"),
    }
    call = _call(definition, args, nested=nested, call_id="save")
    model = scripted_model(turns=[ToolTurn((call,)), "The save request finished."])
    provider = AsyncMock()
    provider.post.return_value = {"uploadUrl": UPLOAD_URL}
    provider.upload_fragment.return_value = file_metadata(
        name="saved.xlsx",
        size=len(content),
        parentReference={"driveId": "drive", "path": "/drives/drive/root:"},
        file={"mimeType": XLSX, "hashes": {"quickXorHash": quickxorhash(content)}},
    )
    credentials = AsyncMock(return_value=provider)
    monkeypatch.setattr("integrations.sharepoint.tools.write_utils.drive_client", credentials)
    suspended = await run_scenario(db_session_factory, context, model=model)
    assert suspended.run.status == "awaiting_approval"
    state = load_suspended_run_state(suspended.run)
    pin = state.deferred_tool_requests.metadata["save"]["display_args"]["_source"]
    assert pin == {
        "file_id": str(file.id),
        "revision_id": str(revision.id),
        "content_hash": sha256_hex(content),
        "name": "reviewed.xlsx",
        "content_type": XLSX,
        "size_bytes": len(content),
    }
    credentials.assert_not_awaited()
    decision = AgentRunResumeDecision(
        tool_call_id="save:1" if nested else "save", decision="approved"
    )
    if outcome == "source_changed":
        await _append_revision(db_session_factory, context, file.id, _edited_workbook())
    elif outcome == "deleted":
        async with db_session_factory() as db:
            stored = await db.get(File, file.id)
            stored.deleted = True
            await db.commit()
    elif outcome == "substituted":
        substitute, _ = await _source_file(context, _edited_workbook())
        decision.override_args = args | {
            "source": SourceReference(entity_id=substitute.id, label="Replacement").model_dump(
                mode="json"
            )
        }

    if outcome in {"deleted", "substituted"}:
        with pytest.raises(AppValidationError) as caught:
            await resume_scenario(db_session_factory, context, model=model, decisions=[decision])
        if outcome == "substituted":
            assert caught.value.details["locked_fields"] == ["source"]
        else:
            assert caught.value.field == "source"
        credentials.assert_not_awaited()
        assert provider.mock_calls == []
        async with db_session_factory() as db:
            pending = await db.get(AgentRun, context.run_id)
            assert pending.status == "awaiting_approval"
            assert (
                load_suspended_run_state(pending).deferred_tool_requests.metadata["save"][
                    "display_args"
                ]["_source"]
                == pin
            )
        return

    compiled = await _compile_source_decision(db_session_factory, context, decision)
    canonical = (
        compiled.metadata["save"]["code_mode_decision"]["effective_args"]
        if nested
        else compiled.approvals["save"].override_args
    )
    assert canonical["source"]["entity_id"] == str(file.id)
    assert canonical["source"]["label"] == "reviewed.xlsx"
    assert canonical["source"]["description"] != "Untrusted description"
    async with db_session_factory() as db:
        pending = await db.get(AgentRun, context.run_id)
        assert (
            load_suspended_run_state(pending).deferred_tool_requests.metadata["save"][
                "display_args"
            ]["_source"]
            == pin
        )
    completed = await resume_scenario(
        db_session_factory, context, model=model, decisions=[decision]
    )
    assert completed.run.status == "completed"
    operations = [
        row for row in completed.audit_rows if row.details.get("provider_operation") == "write_file"
    ]
    if outcome == "source_changed":
        assert [row.status for row in operations] == ["failure"]
        assert operations[0].details["error_code"] == "source_changed"
        credentials.assert_not_awaited()
        assert provider.mock_calls == []
    else:
        assert sorted(row.status for row in operations) == ["pending", "success"]
        provider.upload_fragment.assert_awaited_once()
        assert provider.upload_fragment.await_args.args[1] == content


@pytest.mark.parametrize("nested", [False, True], ids=["direct", "code_mode"])
@pytest.mark.parametrize("visibility", ["foreign", "platform", "deleted"])
async def test_unavailable_file_sources_cannot_produce_usable_approval(
    db_session_factory, monkeypatch, document_storage, nested, visibility
):
    definition = replace(WRITE_DEFINITION, availability_check=lambda: True)
    _configure_runtime(
        monkeypatch,
        db_session_factory,
        ((definition, "approval"),),
        nested=nested,
        real_entities=True,
    )
    context = await build_scenario_agent(
        db_session_factory, tool_names=[definition.name], code_mode_enabled=nested
    )
    file, _ = await _source_file(context, WORKBOOK.read_bytes(), visibility=visibility)
    source = SourceReference(entity_id=file.id, label="Claimed workspace File")
    call = _call(
        definition,
        {"name": "saved.xlsx", "source": source.model_dump(mode="json")},
        nested=nested,
        call_id="save",
    )
    model = scripted_model(turns=[ToolTurn((call,)), "The request finished."])
    credentials = AsyncMock()
    monkeypatch.setattr("integrations.sharepoint.tools.write_utils.drive_client", credentials)
    storage = AsyncMock()
    monkeypatch.setattr(
        importlib.import_module("services.integrations.files.read_file_source"),
        "get_storage_provider",
        storage,
    )
    suspended = await run_scenario(db_session_factory, context, model=model)
    assert suspended.run.status == "awaiting_approval"
    display = load_suspended_run_state(suspended.run).deferred_tool_requests.metadata["save"][
        "display_args"
    ]
    assert "_source" not in display
    assert "_approval_display_error" in display
    decision = AgentRunResumeDecision(
        tool_call_id="save:1" if nested else "save", decision="approved"
    )
    if visibility == "platform":
        completed = await resume_scenario(
            db_session_factory, context, model=model, decisions=[decision]
        )
        assert completed.run.status == "completed"
        operations = [
            row
            for row in completed.audit_rows
            if row.details.get("provider_operation") == "write_file"
        ]
        assert [row.status for row in operations] == ["failure"]
        assert operations[0].details["error_code"] == "ModelRetry"
        assert "The approved details are unavailable" in str(
            [message.parts for message in completed.messages]
        )
    else:
        with pytest.raises(AppValidationError) as caught:
            await resume_scenario(db_session_factory, context, model=model, decisions=[decision])
        assert caught.value.field == "source"
    credentials.assert_not_awaited()
    storage.assert_not_called()
