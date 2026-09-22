"""Committed copies retain cleanup ownership and truthful transaction evidence."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from importlib import import_module
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from integrations.sharepoint.references import SharePointDriveItemReference
from integrations.sharepoint.tools.copy_to_files import DEFINITION
from models.audit_event import AuditEvent
from models.files import File, FileFolder, FileReference, FileUpload
from services.agents.runtime.code_mode.stubs import CodeModeCatalog
from services.agents.runtime.tools.code_mode import RUN_WORKFLOW_TOOL_NAME, build_run_workflow_tool
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.integrations.context.domain import ResolvedActiveContext
from services.jobs.handlers.sweep_deleted_files import _purge_expired_uploads
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider
from tests.integrations.sharepoint.support import entry, file_metadata
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    next_scenario_run,
    run_scenario,
    scripted_model,
)
from tests.support.storage import reset_storage_provider_cache

CONTENT = b"Copied content"


@pytest.fixture
async def copy_runtime(committed_db_session_factory, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    reset_storage_provider_cache()
    definition = replace(DEFINITION, availability_check=lambda: True)
    monkeypatch.setitem(RUNTIME_TOOL_CATALOG, definition.name, definition)
    monkeypatch.setattr(
        "services.agents.runtime.loop.build_runtime_tools",
        lambda *_args, **_kwargs: [definition.to_pydantic_tool(policy="auto")],
    )
    monkeypatch.setattr(
        "services.agents.runtime.execute.setup.resolve_active_context",
        AsyncMock(return_value=ResolvedActiveContext(entries=(entry(),))),
    )
    provider = AsyncMock()
    provider.get.return_value = file_metadata(size=len(CONTENT))
    provider.get_bytes.return_value = CONTENT
    monkeypatch.setattr(
        "integrations.sharepoint.tools.copy_to_files.drive_client",
        AsyncMock(return_value=provider),
    )
    context = await build_scenario_agent(
        committed_db_session_factory,
        tool_names=[DEFINITION.name],
        tool_policies={DEFINITION.name: "auto"},
    )
    try:
        yield committed_db_session_factory, context
    finally:
        reset_storage_provider_cache()


async def _run_copy(factory, context, *, nested=False):
    args = {
        "file": SharePointDriveItemReference(drive_id="drive", item_id="file").model_dump(
            mode="json"
        ),
        "folder": "Copied documents",
    }
    call = (
        ToolCall(
            RUN_WORKFLOW_TOOL_NAME,
            {"code": f"try:\n    await {DEFINITION.name}(**{args!r})\nexcept Exception:\n    pass"},
            "workflow",
        )
        if nested
        else ToolCall(DEFINITION.name, args, "copy")
    )
    return await run_scenario(
        factory,
        context,
        model=scripted_model(turns=[ToolTurn((call,)), "Done."]),
    )


async def _state(factory, workspace_id):
    async with factory() as db:
        rows = {}
        for model in (File, FileFolder, FileReference, FileUpload, AuditEvent):
            rows[model] = list(
                await db.scalars(select(model).where(model.workspace_id == workspace_id))
            )
        return rows


async def _sweep(factory, workspace_id):
    async with factory() as db:
        uploads = list(
            await db.scalars(select(FileUpload).where(FileUpload.workspace_id == workspace_id))
        )
        for upload in uploads:
            upload.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
        await _purge_expired_uploads(db, now=datetime.now(UTC))
        await db.commit()


@pytest.mark.parametrize("failure", ["link", "cancel_link", "commit", "lost_commit"])
@pytest.mark.parametrize("nested", [False, True])
async def test_copy_failure_owns_bytes_through_commit(copy_runtime, monkeypatch, failure, nested):
    tool = import_module("services.integrations.files.create_copy")

    factory, context = copy_runtime
    original_link = tool.create_conversation_file_references
    original_commit = AsyncSession.commit
    if nested:
        definition = RUNTIME_TOOL_CATALOG[DEFINITION.name]
        monkeypatch.setattr(
            "services.agents.runtime.loop.build_runtime_tools",
            lambda *_args, **_kwargs: [
                build_run_workflow_tool(CodeModeCatalog.build(((definition, "auto"),)))
            ],
        )
        from models.agent import Agent

        async with factory() as db:
            agent = await db.get(Agent, context.agent_id)
            agent.code_mode_enabled = True
            await db.commit()

    async def link(db, **kwargs):
        await original_link(db, **kwargs)
        if failure == "link":
            raise RuntimeError("Link unavailable")
        if failure == "cancel_link":
            raise asyncio.CancelledError
        db.info["inject_copy_commit"] = True

    async def commit(db):
        if db.info.pop("inject_copy_commit", False):
            if failure == "lost_commit":
                await original_commit(db)
            raise RuntimeError("Commit response unavailable")
        await original_commit(db)

    monkeypatch.setattr(tool, "create_conversation_file_references", link)
    monkeypatch.setattr(AsyncSession, "commit", commit)
    try:
        result = await _run_copy(factory, context, nested=nested)
        if nested and failure in {"commit", "lost_commit"}:
            assert result.run.status == "completed"
    except asyncio.CancelledError:
        assert failure == "cancel_link"
    except RuntimeError as exc:
        assert failure in {"commit", "lost_commit"}
        assert str(exc) == "Commit response unavailable"
    rows = await _state(factory, context.workspace_id)
    [reservation] = rows[FileUpload]
    ref = make_storage_object_ref(StorageBucket.PRIVATE, reservation.object_key)
    assert await get_storage_provider().get_object(ref) == CONTENT
    success = [
        row
        for row in rows[AuditEvent]
        if row.status == "success" and row.tool_name == DEFINITION.name
    ]
    if failure == "lost_commit":
        assert reservation.consumed_at is not None
        assert [file.id for file in rows[File]] == [reservation.file_id]
        assert len(rows[FileReference]) == 1
        assert len(success) == 1
        assert success[0].details["provider_operation"] == "copy_to_files"
    else:
        assert reservation.consumed_at is None
        assert rows[File] == rows[FileFolder] == rows[FileReference] == []
        assert not [row for row in success if row.details.get("provider_operation")]
        if failure == "commit":
            assert success == []
    await _sweep(factory, context.workspace_id)
    assert (await get_storage_provider().stat_object(ref) is not None) == (failure == "lost_commit")
    remaining = await _state(factory, context.workspace_id)
    assert len(remaining[FileUpload]) == (1 if failure == "lost_commit" else 0)


async def test_copy_retry_and_cleanup_failure_preserve_ownership(copy_runtime, monkeypatch):
    tool = import_module("services.integrations.files.create_copy")

    factory, context = copy_runtime
    original_link = tool.create_conversation_file_references
    monkeypatch.setattr(
        tool,
        "create_conversation_file_references",
        AsyncMock(side_effect=RuntimeError("Link unavailable")),
    )
    await _run_copy(factory, context)
    rows = await _state(factory, context.workspace_id)
    [failed] = rows[FileUpload]
    failed_ref = make_storage_object_ref(StorageBucket.PRIVATE, failed.object_key)
    monkeypatch.setattr(tool, "create_conversation_file_references", original_link)
    retry = await next_scenario_run(factory, context)
    result = await _run_copy(factory, retry)
    assert result.run.status == "completed"
    rows = await _state(factory, context.workspace_id)
    assert len(rows[File]) == 1 and len(rows[FileUpload]) == 2
    [consumed] = [row for row in rows[FileUpload] if row.consumed_at is not None]
    kept_ref = make_storage_object_ref(StorageBucket.PRIVATE, consumed.object_key)
    provider = get_storage_provider()
    original_delete = provider.delete_object
    monkeypatch.setattr(
        provider, "delete_object", AsyncMock(side_effect=OSError("Storage unavailable"))
    )
    await _sweep(factory, context.workspace_id)
    assert len((await _state(factory, context.workspace_id))[FileUpload]) == 2
    assert await provider.get_object(failed_ref) == CONTENT
    monkeypatch.setattr(provider, "delete_object", original_delete)
    await _sweep(factory, context.workspace_id)
    assert await provider.stat_object(failed_ref) is None
    assert await provider.get_object(kept_ref) == CONTENT
    assert len((await _state(factory, context.workspace_id))[FileUpload]) == 1


async def test_cancelled_write_keeps_cleanup_lock_until_provider_settles(copy_runtime, monkeypatch):
    factory, context = copy_runtime
    provider = get_storage_provider()
    original_put = provider.put_object
    started, finish = asyncio.Event(), asyncio.Event()

    async def slow_put(*args, **kwargs):
        result = await original_put(*args, **kwargs)
        started.set()
        await finish.wait()
        return result

    monkeypatch.setattr(provider, "put_object", slow_put)
    task = asyncio.create_task(_run_copy(factory, context))
    try:
        async with asyncio.timeout(10):
            await started.wait()
            task.cancel()
            async with factory() as db:
                await _purge_expired_uploads(db, now=datetime.now(UTC) + timedelta(days=30))
                await db.commit()
            rows = await _state(factory, context.workspace_id)
            [reservation] = rows[FileUpload]
            ref = make_storage_object_ref(StorageBucket.PRIVATE, reservation.object_key)
            assert await provider.get_object(ref) == CONTENT
            assert not task.done()
            finish.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        rows = await _state(factory, context.workspace_id)
        assert rows[File] == [] and rows[FileUpload][0].consumed_at is None
        await _sweep(factory, context.workspace_id)
        assert await provider.stat_object(ref) is None
    finally:
        finish.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_reservation_does_not_commit_unrelated_tool_changes(copy_runtime):
    from models.workspace import Workspace
    from services.files.reserve_file_revision import reserve_file_revision

    factory, context = copy_runtime
    async with factory() as db:
        workspace = await db.get(Workspace, context.workspace_id)
        original_name = workspace.name
        workspace.name = "Uncommitted name"
        reservation = await reserve_file_revision(
            db,
            workspace_id=context.workspace_id,
            user_id=context.user_id,
            name="notes.txt",
            content=CONTENT,
            content_type="text/plain",
            extension=".txt",
        )
        reservation_id = reservation.id
        async with factory() as observer:
            assert (await observer.get(Workspace, context.workspace_id)).name == original_name
            assert await observer.get(FileUpload, reservation_id) is not None
        await db.rollback()
    await _sweep(factory, context.workspace_id)
    assert (await _state(factory, context.workspace_id))[FileUpload] == []


async def test_copy_audit_failure_rolls_back_local_effects(copy_runtime, monkeypatch):
    import services.integrations.operations as operations

    factory, context = copy_runtime
    original_record = operations.record_integration_operation_audit_event

    async def record(**kwargs):
        if kwargs.get("db") is not None:
            raise RuntimeError("Audit unavailable")
        return await original_record(**kwargs)

    monkeypatch.setattr(operations, "record_integration_operation_audit_event", record)
    await _run_copy(factory, context)
    rows = await _state(factory, context.workspace_id)
    assert rows[File] == rows[FileFolder] == rows[FileReference] == []
    [reservation] = rows[FileUpload]
    assert reservation.consumed_at is None
    assert not [
        event
        for event in rows[AuditEvent]
        if event.status == "success" and event.details.get("provider_operation")
    ]
    await _sweep(factory, context.workspace_id)
