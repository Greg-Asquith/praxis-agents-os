"""Governed image editing and video-to-image runtime scenarios."""

import base64
from collections.abc import Iterator
from hashlib import sha256

import pytest
from pydantic import SecretStr
from pydantic_ai import DeferredToolResults, ToolApproved
from pydantic_ai.messages import BinaryImage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.settings import settings
from models.audit_event import AuditEvent
from models.files import File, FileRevision
from models.workspace import Workspace
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.entity_references.domain import FileReference
from services.agents.runtime.tools.native import (
    image_editing as image_editing_tools,
    video_to_image as video_to_image_tools,
)
from services.files.contract import FileCategory
from services.files.utils import private_ref_from_key
from services.storage.factory import get_storage_provider
from tests.factories import build_file, build_file_revision
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)
from tests.support.storage import reset_storage_provider_cache

_ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


@pytest.fixture
def image_input_storage(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    reset_storage_provider_cache()
    try:
        yield
    finally:
        reset_storage_provider_cache()


def _enable_google(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", False)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", SecretStr("google-test"))
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)


async def _persist_source(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    workspace_id,
    user_id,
    name: str,
    category: FileCategory,
    content_type: str,
    extension: str,
    content: bytes,
) -> tuple[File, FileRevision]:
    async with session_factory() as db:
        workspace = await db.get_one(Workspace, workspace_id)
        digest = sha256(content).hexdigest()
        file = build_file(
            workspace=workspace,
            name=name,
            category=category.value,
            content_type=content_type,
            extension=extension,
            size_bytes=len(content),
            content_hash=digest,
        )
        db.add(file)
        await db.flush()
        revision = build_file_revision(
            file,
            created_by_user_id=user_id,
            size_bytes=len(content),
            content_hash=digest,
        )
        await get_storage_provider().put_object(
            private_ref_from_key(revision.object_key),
            content,
            content_type=content_type,
        )
        db.add(revision)
        await db.flush()
        file.current_revision_id = revision.id
        file.revision_count = 1
        await db.commit()
        return file, revision


@pytest.mark.parametrize("tool_name", ["edit_image", "generate_image_from_video"])
async def test_input_media_tool_approval_resumes_with_edited_prompt(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    image_input_storage: None,
    tool_name: str,
) -> None:
    _enable_google(monkeypatch)
    calls: list[tuple[str, list[bytes]]] = []

    async def fake_generate(*, prompt, input_media, **_kwargs) -> BinaryImage:
        calls.append((prompt, [item.data for item in input_media]))
        return BinaryImage(data=_ONE_PIXEL_PNG, media_type="image/png")

    tool_module = image_editing_tools if tool_name == "edit_image" else video_to_image_tools
    monkeypatch.setattr(tool_module, "run_native_image_generation", fake_generate)
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[tool_name],
        tool_policies={tool_name: "approval"},
    )
    is_edit = tool_name == "edit_image"
    source, _revision = await _persist_source(
        db_session_factory,
        workspace_id=context.workspace_id,
        user_id=context.user_id,
        name="source.png" if is_edit else "source.mp4",
        category=FileCategory.IMAGE if is_edit else FileCategory.VIDEO,
        content_type="image/png" if is_edit else "video/mp4",
        extension=".png" if is_edit else ".mp4",
        content=b"source-image" if is_edit else b"source-video",
    )
    reference = FileReference(entity_id=source.id, label=source.name).model_dump(mode="json")
    args = (
        {"prompt": "Original prompt", "file_ids": [reference], "model_provider": "google"}
        if is_edit
        else {"prompt": "Original prompt", "file_id": reference}
    )
    model = scripted_model(
        turns=[ToolTurn((ToolCall(tool_name, args, "media-approval"),)), "The image is ready."]
    )

    suspended = await run_scenario(db_session_factory, context, model=model)

    assert suspended.run.status == RUN_STATUS_AWAITING_APPROVAL
    assert calls == []
    state = load_suspended_run_state(suspended.run)
    resumed_args = {**args, "prompt": "Approved prompt"}
    resumed = await run_scenario(
        db_session_factory,
        context,
        model=model,
        prompt=None,
        expected_status=RUN_STATUS_AWAITING_APPROVAL,
        message_history=state.message_history,
        deferred_tool_results=DeferredToolResults(
            approvals={state.pending_tool_call_ids[0]: ToolApproved(override_args=resumed_args)}
        ),
    )

    assert resumed.run.status == "completed"
    assert calls == [
        (
            "Approved prompt",
            [b"source-image" if is_edit else b"source-video"],
        )
    ]
    assert {row.details["outcome"] for row in resumed.audit_rows if row.tool_name == tool_name} == {
        "approval_requested",
        "completed",
    }


@pytest.mark.parametrize("tool_name", ["edit_image", "generate_image_from_video"])
async def test_input_media_tool_auto_path_persists_source_provenance(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    image_input_storage: None,
    tool_name: str,
) -> None:
    _enable_google(monkeypatch)

    async def fake_generate(**_kwargs) -> BinaryImage:
        return BinaryImage(data=_ONE_PIXEL_PNG, media_type="image/png")

    tool_module = image_editing_tools if tool_name == "edit_image" else video_to_image_tools
    monkeypatch.setattr(tool_module, "run_native_image_generation", fake_generate)
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[tool_name],
        tool_policies={tool_name: "auto"},
    )
    is_edit = tool_name == "edit_image"
    source, source_revision = await _persist_source(
        db_session_factory,
        workspace_id=context.workspace_id,
        user_id=context.user_id,
        name="source.png" if is_edit else "source.mp4",
        category=FileCategory.IMAGE if is_edit else FileCategory.VIDEO,
        content_type="image/png" if is_edit else "video/mp4",
        extension=".png" if is_edit else ".mp4",
        content=b"source-image" if is_edit else b"source-video",
    )
    source_files = [(source, source_revision)]
    if is_edit:
        second_source = await _persist_source(
            db_session_factory,
            workspace_id=context.workspace_id,
            user_id=context.user_id,
            name="style.png",
            category=FileCategory.IMAGE,
            content_type="image/png",
            extension=".png",
            content=b"style-image",
        )
        source_files.append(second_source)
    references = [
        FileReference(entity_id=file.id, label=file.name).model_dump(mode="json")
        for file, _revision in source_files
    ]
    args = (
        {"prompt": "Approved prompt", "file_ids": references, "model_provider": "google"}
        if is_edit
        else {"prompt": "Approved prompt", "file_id": references[0]}
    )
    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(turns=[ToolTurn((ToolCall(tool_name, args, "media-auto"),)), "Done."]),
    )

    assert result.run.status == "completed"
    async with db_session_factory() as db:
        generated = list(
            (
                await db.scalars(
                    select(File).where(
                        File.workspace_id == context.workspace_id,
                        File.id.not_in([file.id for file, _revision in source_files]),
                    )
                )
            ).all()
        )
        assert len(generated) == 1
        [file_audit] = list(
            (
                await db.scalars(
                    select(AuditEvent).where(
                        AuditEvent.workspace_id == context.workspace_id,
                        AuditEvent.resource_id == str(generated[0].id),
                    )
                )
            ).all()
        )
    assert file_audit.details["input_file_ids"] == [
        str(file.id) for file, _revision in source_files
    ]
    assert file_audit.details["input_revision_ids"] == [
        str(revision.id) for _file, revision in source_files
    ]
    assert file_audit.details["source"] == (
        "native_image_editing" if is_edit else "native_video_to_image"
    )
