"""Retained results stay complete, hidden, and stable across real runtime turns."""

import asyncio
import importlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import set_session_tenant_context
from core.exceptions.general import NotFoundError
from core.settings import settings
from models.conversation import Conversation
from models.files import File, FileFolder, FileRevision, FileUpload
from models.workspace import Workspace
from services.agents.runtime.entity_references.domain import FileReference
from services.agents.runtime.entity_references.registry import get_entity_resolver
from services.agents.runtime.load_context import load_available_files
from services.agents.runtime.tools.native.run_code_file_bridge import (
    build_run_code_prompt,
    load_run_code_inputs,
)
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG, runtime_tool
from services.files.append_file_revision import append_file_revision
from services.files.get_files_processing_summary import get_files_processing_summary
from services.files.list_files import list_files
from services.files.revision_actor import FileRevisionActor
from services.files.utils import file_revision_ref, get_visible_file
from services.jobs.handlers.sweep_deleted_files import _purge_expired_uploads
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    next_scenario_run,
    run_scenario,
    scripted_model,
)
from tests.support.storage import reset_storage_provider_cache

ROWS = [{"id": i, "value": i * 2, "text": "検索 example " * 25} for i in range(1_000)]
RESULT = {"rows": ROWS, "total_rows": len(ROWS), "currency": "GBP"}


class ReportOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[dict]
    total_rows: int
    currency: str


@pytest.fixture
def retained_tools(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "AGENT_STRUCTURED_RESULT_MAX_CHARS", 48_000)
    monkeypatch.setattr(settings, "AGENT_RESULT_PREVIEW_ROWS", 40)
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    reset_storage_provider_cache()

    @runtime_tool(
        name="retained_report",
        provider="test",
        description="Return a complete synthetic report.",
        output_model=ReportOutput,
        code_eligible=True,
    )
    async def retained_report(small: bool = False, typed: bool = False) -> dict | ReportOutput:
        value = {**RESULT, "rows": ROWS[:1], "total_rows": 1} if small else RESULT
        return ReportOutput.model_validate(value) if typed else value

    yield
    RUNTIME_TOOL_CATALOG.pop("retained_report", None)
    reset_storage_provider_cache()


@pytest.mark.parametrize("typed", [False, True])
async def test_retained_rows_are_hidden_readable_and_stable(
    db_session_factory, retained_tools, typed
):
    context = await build_scenario_agent(db_session_factory, tool_names=["retained_report"])
    seen = []
    first = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn((ToolCall("retained_report", {"typed": typed}, "report-1"),)),
                "Report ready.",
            ],
            seen_requests=seen,
        ),
    )
    assert first.run.status == "completed"
    [returned] = first.tool_returns("retained_report")
    preview = returned["content"]
    assert preview["preview"] is True
    assert preview["lists"]["rows"] == {"total": 1_000, "shown": 40}
    assert len(json.dumps(preview, ensure_ascii=False)) < settings.AGENT_STRUCTURED_RESULT_MAX_CHARS
    assert str(ROWS[-1]) not in str(seen[-1][0])
    event = next(
        e for e in first.events if e.event == "tool.result" and e.data["name"] == "retained_report"
    )
    assert event.data["result"] == preview
    audit = next(a for a in first.audit_rows if a.resource_type == "tool_call")
    assert audit.details["result_file_id"] == preview["file_id"]
    assert audit.details["result_original_chars"] > audit.details["result_chars"]
    assert audit.details["result_truncated"] is False
    async with db_session_factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context.workspace_id, user_id=context.user_id
        )
        file = await db.get(File, UUID(preview["file_id"]))
        assert file.is_tool_result is True
        assert file.folder_id is None
        revision = await db.get(FileRevision, file.current_revision_id)
        stored = await get_storage_provider().get_object(file_revision_ref(revision))
        assert json.loads(stored) == RESULT
        workspace = await db.get(Workspace, context.workspace_id)
        assert (await list_files(db, workspace=workspace)).total == 0
        assert (await list_files(db, workspace=workspace, search=file.name)).total == 0
        assert (await get_files_processing_summary(db, workspace=workspace)).ready == 0
        assert await db.scalar(select(func.count()).select_from(FileFolder)) == 0
        conversation = await db.get(Conversation, context.conversation_id)
        assert await load_available_files(db, conversation) == []
        ctx = SimpleNamespace(
            deps=SimpleNamespace(db=db, workspace=workspace, conversation=conversation)
        )
        resolver = get_entity_resolver("file")
        resolver_ctx = SimpleNamespace(db=db, workspace=workspace)
        assert (await resolver.search(resolver_ctx, "", {}, 25, None)).choices == ()
        assert len(await resolver.resolve(resolver_ctx, [preview["file_reference"]], {})) == 1
        [input_file] = await load_run_code_inputs(
            ctx, [FileReference.model_validate(preview["file_reference"])]
        )
        assert json.loads(input_file.content) == RESULT
        prompt = await build_run_code_prompt("Sum every value.", [input_file], provider="openai")
        assert input_file.sandbox_name in prompt
        assert ROWS[-1]["text"] not in prompt
        await append_file_revision(
            db,
            workspace=workspace,
            file_id=file.id,
            content=b'{"rows": []}',
            actor=FileRevisionActor(user_id=context.user_id),
        )
        await db.commit()
        [pinned_input] = await load_run_code_inputs(
            ctx, [FileReference.model_validate(preview["file_reference"])]
        )
        assert pinned_input.revision_id == revision.id
        assert pinned_input.content == stored

    followup_seen = []
    followup = await run_scenario(
        db_session_factory,
        await next_scenario_run(db_session_factory, context),
        model=scripted_model(
            turns=[
                ToolTurn(
                    (
                        ToolCall(
                            "read_file",
                            {
                                "file_id": preview["file_reference"],
                                "offset": len(stored) - 600,
                                "max_bytes": 600,
                            },
                        ),
                    )
                ),
                "The final row is available.",
            ],
            seen_requests=followup_seen,
        ),
        prompt="Inspect the end of that report.",
    )
    assert followup.run.status == "completed"
    assert followup.tool_returns("retained_report")[0]["content"] == preview
    read = followup.tool_returns("read_file")[0]["content"]["content"]
    assert read["node"] == "praxis_untrusted"
    assert '"id":999' in read["content"]
    assert len(str(followup_seen[0][0])) < 48_000
    other = await build_scenario_agent(db_session_factory)
    async with db_session_factory() as db:
        await set_session_tenant_context(db, workspace_id=other.workspace_id, user_id=other.user_id)
        with pytest.raises(NotFoundError):
            await get_visible_file(
                db, workspace_id=other.workspace_id, file_id=UUID(preview["file_id"])
            )
        assert await db.get(File, UUID(preview["file_id"])) is None


@pytest.mark.parametrize("public_limit", [2_000, 2_000_000])
async def test_public_budget_and_stream_preview_are_independent(
    db_session_factory, retained_tools, public_limit
):
    RUNTIME_TOOL_CATALOG["retained_report"] = replace(
        RUNTIME_TOOL_CATALOG["retained_report"], max_public_result_chars=public_limit
    )
    context = await build_scenario_agent(db_session_factory, tool_names=["retained_report"])
    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(turns=[ToolTurn((ToolCall("retained_report", {}),)), "Ready."]),
    )
    assert result.run.status == "completed"
    returned = result.tool_returns("retained_report")[0]
    public = returned["metadata"].get("public_result")
    if public_limit > len(json.dumps(RESULT)):
        assert public == RESULT
    else:
        assert public is None
    event = next(e for e in result.events if e.event == "tool.result")
    assert event.data["result"] == returned["content"]
    assert event.data["result"]["preview"] is True
    assert len(json.dumps(event.data["result"], ensure_ascii=False, separators=(",", ":"))) <= min(
        public_limit, settings.AGENT_STRUCTURED_RESULT_MAX_CHARS
    )


@pytest.mark.parametrize("failure", ["save", "size", "commit"])
async def test_storage_failures_retry_without_incomplete_success(
    db_session_factory, retained_tools, monkeypatch, failure
):
    if failure == "commit":
        dispatch = importlib.import_module("services.agents.runtime.dispatch")
        save = dispatch.save_tool_result

        async def save_then_fail_commit(deps, **kwargs):
            saved = await save(deps, **kwargs)
            commit = deps.db.commit

            async def fail_once():
                deps.db.commit = commit
                raise RuntimeError("commit failed")

            deps.db.commit = fail_once
            return saved

        monkeypatch.setattr(dispatch, "save_tool_result", save_then_fail_commit)
    elif failure == "save":
        dispatch = importlib.import_module("services.agents.runtime.dispatch")
        monkeypatch.setattr(
            dispatch, "save_tool_result", AsyncMock(side_effect=OSError("private backend detail"))
        )
    else:
        monkeypatch.setattr(settings, "MAX_FILE_SIZE_AGENT_FILE", 1_000)
    context = await build_scenario_agent(db_session_factory, tool_names=["retained_report"])
    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[ToolTurn((ToolCall("retained_report", {}),)), "Please narrow the report."]
        ),
    )
    retries = [e for e in result.events if e.event == "tool.result"]
    assert retries[0].data["outcome"] == "retry"
    assert ("could not be retained" if failure == "commit" else "too large") in str(
        retries[0].data["result"]
    )
    assert "private backend detail" not in str(retries[0].data)
    assert not result.tool_returns("retained_report")
    async with db_session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(File)) == 0


async def test_small_result_is_unchanged(db_session_factory, retained_tools):
    context = await build_scenario_agent(db_session_factory, tool_names=["retained_report"])
    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[ToolTurn((ToolCall("retained_report", {"small": True}),)), "Done."]
        ),
    )
    assert result.tool_returns("retained_report")[0]["content"] == {
        **RESULT,
        "rows": ROWS[:1],
        "total_rows": 1,
    }
    async with db_session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(File)) == 0


async def test_code_mode_receives_all_rows(db_session_factory, retained_tools):
    context = await build_scenario_agent(
        db_session_factory, tool_names=["retained_report"], code_mode_enabled=True
    )
    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn(
                    (
                        ToolCall(
                            "run_workflow",
                            {
                                "code": "report = await retained_report()\n{'total': sum(row['value'] for row in report['rows']), 'rows': len(report['rows'])}"
                            },
                        ),
                    )
                ),
                "Computed every row.",
            ]
        ),
    )
    assert result.run.status == "completed"
    returned = result.tool_returns("run_workflow")[0]
    assert returned["content"] == {"total": 999_000, "rows": 1_000}
    async with db_session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(File)) == 0


@pytest.mark.parametrize(
    "failure", ["link", "cancel_link", "write", "commit", "cancel_commit", "lost_commit", None]
)
async def test_retained_upload_ownership_survives_transaction_failure(
    committed_db_session_factory, retained_tools, monkeypatch, failure
):
    factory = committed_db_session_factory
    context = await build_scenario_agent(factory, tool_names=["retained_report"])
    service = importlib.import_module("services.files.save_tool_result")
    original_link = service.create_conversation_file_references
    original_commit = AsyncSession.commit
    provider = get_storage_provider()
    original_put = provider.put_object

    async def link(db, **kwargs):
        await original_link(db, **kwargs)
        if failure == "link":
            raise RuntimeError("Reference unavailable")
        if failure == "cancel_link":
            raise asyncio.CancelledError
        db.info["inject_retained_commit"] = True

    async def commit(db):
        if db.info.pop("inject_retained_commit", False):
            if failure == "cancel_commit":
                raise asyncio.CancelledError
            if failure == "lost_commit":
                await original_commit(db)
            if failure in {"commit", "lost_commit"}:
                raise RuntimeError("Commit response unavailable")
        await original_commit(db)

    async def put(*args, **kwargs):
        await original_put(*args, **kwargs)
        raise OSError("Write response unavailable")

    monkeypatch.setattr(service, "create_conversation_file_references", link)
    monkeypatch.setattr(AsyncSession, "commit", commit)
    if failure == "write":
        monkeypatch.setattr(provider, "put_object", put)
    try:
        result = await run_scenario(
            factory,
            context,
            model=scripted_model(turns=[ToolTurn((ToolCall("retained_report", {}),)), "Done."]),
        )
        assert bool(result.tool_returns("retained_report")) == (failure is None)
    except asyncio.CancelledError:
        assert failure in {"cancel_link", "cancel_commit"}

    committed = failure in {None, "lost_commit"}
    async with factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context.workspace_id, user_id=context.user_id
        )
        [reservation] = list(
            await db.scalars(
                select(FileUpload).where(FileUpload.workspace_id == context.workspace_id)
            )
        )
        assert (reservation.consumed_at is not None) == committed
        assert (await db.get(File, reservation.file_id) is not None) == committed
        ref = make_storage_object_ref(StorageBucket.PRIVATE, reservation.object_key)
        assert json.loads(await provider.get_object(ref)) == RESULT
        reservation.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
        if not committed:
            with monkeypatch.context() as patch:
                patch.setattr(provider, "delete_object", AsyncMock(side_effect=OSError("Offline")))
                await _purge_expired_uploads(db, now=datetime.now(UTC))
                await db.commit()
            assert await db.get(FileUpload, reservation.id) is not None
            assert await provider.stat_object(ref) is not None
        await _purge_expired_uploads(db, now=datetime.now(UTC))
        await db.commit()
        assert (await provider.stat_object(ref) is not None) == committed
        assert (await db.get(FileUpload, reservation.id) is not None) == committed


async def test_retained_cancelled_upload_keeps_cleanup_lock_until_write_finishes(
    committed_db_session_factory, retained_tools, monkeypatch
):
    factory = committed_db_session_factory
    context = await build_scenario_agent(factory, tool_names=["retained_report"])
    provider = get_storage_provider()
    original_put = provider.put_object
    started, finish = asyncio.Event(), asyncio.Event()

    async def slow_put(*args, **kwargs):
        stored = await original_put(*args, **kwargs)
        started.set()
        await finish.wait()
        return stored

    monkeypatch.setattr(provider, "put_object", slow_put)
    task = asyncio.create_task(
        run_scenario(
            factory,
            context,
            model=scripted_model(turns=[ToolTurn((ToolCall("retained_report", {}),)), "Done."]),
        )
    )
    try:
        async with asyncio.timeout(15):
            await started.wait()
            task.cancel()
            async with factory() as db:
                await set_session_tenant_context(
                    db, workspace_id=context.workspace_id, user_id=context.user_id
                )
                await _purge_expired_uploads(db, now=datetime.now(UTC) + timedelta(days=30))
                await db.commit()
                [reservation] = list(
                    await db.scalars(
                        select(FileUpload).where(FileUpload.workspace_id == context.workspace_id)
                    )
                )
                ref = make_storage_object_ref(StorageBucket.PRIVATE, reservation.object_key)
                assert await provider.stat_object(ref) is not None
                assert not task.done()
                task.cancel()
                await asyncio.sleep(0)
                assert not task.done()
                finish.set()
                with pytest.raises(asyncio.CancelledError):
                    await task
                await _purge_expired_uploads(db, now=datetime.now(UTC) + timedelta(days=30))
                await db.commit()
                assert await provider.stat_object(ref) is None
                assert await db.get(FileUpload, reservation.id) is None
    finally:
        finish.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
