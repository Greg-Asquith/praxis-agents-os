"""Governed image editing and video-to-image runtime scenarios."""

import base64
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from pydantic_ai.messages import BinaryImage, UploadedFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.settings import settings
from models.ai_usage_event import AIUsageEvent
from models.audit_event import AuditEvent
from models.files import File, FileRevision
from models.workspace import Workspace
from services.agents.runtime.entity_references.domain import FileReference
from services.agents.runtime.tools import media_inputs as media_inputs_tools
from services.agents.runtime.tools.native import (
    image_editing as image_editing_tools,
    video_to_image as video_to_image_tools,
)
from services.files.contract import FileCategory
from services.files.utils import private_ref_from_key
from services.gemini_files import GeminiFile
from services.storage.factory import get_storage_provider
from services.storage.providers.gcs import GcsStorageProvider
from tests.factories import build_file, build_file_revision
from tests.support.google_native import mock_google_native
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


@pytest.mark.parametrize(
    ("tool_name", "provider", "image_model"),
    [
        ("edit_image", "google", "gemini-nano-banana-2.1"),
        ("generate_image_from_video", "google", "gemini-nano-banana-2.1"),
    ],
)
async def test_input_media_tool_auto_path_persists_source_provenance(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    image_input_storage: None,
    tool_name: str,
    provider: str,
    image_model: str,
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
        {"prompt": "  Approved prompt  ", "file_ids": references, "model_provider": provider}
        if is_edit
        else {"prompt": "  Approved prompt  ", "file_id": references[0]}
    )
    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(turns=[ToolTurn((ToolCall(tool_name, args, "media-auto"),)), "Done."]),
    )

    assert result.run.status == "completed"
    [returned] = result.tool_returns(tool_name)
    assert returned["content"]["image_model" if is_edit else "model"] == image_model
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


async def test_vertex_edit_gif_fails_before_provider_dispatch(
    db_session_factory, monkeypatch, image_input_storage
):
    _enable_google(monkeypatch)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", True)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", "image-test")
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_LOCATION", "global")
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", None)
    context = await build_scenario_agent(
        db_session_factory, tool_names=["edit_image"], tool_policies={"edit_image": "auto"}
    )
    source, revision = await _persist_source(
        db_session_factory,
        workspace_id=context.workspace_id,
        user_id=context.user_id,
        name="source.gif",
        category=FileCategory.IMAGE,
        content_type="image/gif",
        extension=".gif",
        content=b"GIF89a",
    )
    reference = FileReference(entity_id=source.id, label=source.name).model_dump(mode="json")
    async with mock_google_native(monkeypatch, vertex=True) as requests:
        result = await run_scenario(
            db_session_factory,
            context,
            model=scripted_model(
                turns=[
                    ToolTurn(
                        (
                            ToolCall(
                                "edit_image",
                                {
                                    "prompt": "Add a fox",
                                    "file_ids": [reference],
                                    "model_provider": "google",
                                },
                                "vertex-gif",
                            ),
                        )
                    ),
                    "Convert the source image to PNG, JPEG, or WebP.",
                ]
            ),
        )
    assert requests == []
    assert result.run.status == "completed"
    [audit] = [row for row in result.audit_rows if row.tool_name == "edit_image"]
    assert audit.status == "failure"
    assert "Convert the source image" in str([message.parts for message in result.messages])
    async with db_session_factory() as db:
        assert (
            await db.scalars(select(File.id).where(File.workspace_id == context.workspace_id))
        ).all() == [source.id]
        saved = await db.get_one(File, source.id)
        assert saved.current_revision_id == revision.id
        assert (
            await db.scalar(
                select(AIUsageEvent.id).where(
                    AIUsageEvent.run_id == context.run_id,
                    AIUsageEvent.purpose == "image_generation",
                )
            )
            is None
        )


class _FakeGcsClient:
    def bucket(self, name: str) -> SimpleNamespace:
        return SimpleNamespace(name=name)


def _video_call(file: File, call_id: str) -> ToolTurn:
    reference = FileReference(entity_id=file.id, label=file.name).model_dump(mode="json")
    return ToolTurn(
        (
            ToolCall(
                "generate_image_from_video", {"prompt": "A still", "file_id": reference}, call_id
            ),
        )
    )


async def _video_source(db_session_factory, context) -> tuple[File, FileRevision]:
    return await _persist_source(
        db_session_factory,
        workspace_id=context.workspace_id,
        user_id=context.user_id,
        name="source.mp4",
        category=FileCategory.VIDEO,
        content_type="video/mp4",
        extension=".mp4",
        content=b"source-video",
    )


async def test_vertex_video_reaches_gemini_by_its_workspace_uri(
    db_session_factory, monkeypatch, image_input_storage
):
    _enable_google(monkeypatch)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", "video-test")
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_LOCATION", "global")
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", None)
    gcs = GcsStorageProvider(
        public_bucket_name="praxis-public",
        workspace_bucket_prefix="praxis-test",
        workspace_bucket_location="EU",
        project_id="video-test",
        client=_FakeGcsClient(),
    )
    monkeypatch.setattr(media_inputs_tools, "get_storage_provider", lambda: gcs)
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["generate_image_from_video"],
        tool_policies={"generate_image_from_video": "auto"},
    )
    source, revision = await _video_source(db_session_factory, context)

    async with mock_google_native(monkeypatch, vertex=True) as requests:
        result = await run_scenario(
            db_session_factory,
            context,
            model=scripted_model(turns=[_video_call(source, "vertex-video"), "Done."]),
        )

    assert result.run.status == "completed"
    [request] = requests
    body = request.content.decode()
    assert f"gs://praxis-test-{context.workspace_id}/{revision.object_key}" in body
    assert "inlineData" not in body


async def _cache_upload(db_session_factory, revision_id, *, name: str, expires_at: datetime):
    async with db_session_factory() as db:
        revision = await db.get_one(FileRevision, revision_id)
        revision.gemini_file_name = name
        revision.gemini_file_uri = f"https://generativelanguage.googleapis.com/v1beta/{name}"
        revision.gemini_file_expires_at = expires_at
        await db.commit()


def _gemini_api_video(monkeypatch) -> tuple[list[str], list[object], list[str]]:
    """Sends every video through the Files API and records uploads, inputs, and deletions."""
    _enable_google(monkeypatch)
    monkeypatch.setattr(settings, "NATIVE_VIDEO_TO_IMAGE_MAX_INPUT_BYTES", 4)
    uploads: list[str] = []
    inputs: list[object] = []
    deleted: list[str] = []

    async def fake_upload(ref, **_kwargs) -> GeminiFile:
        uploads.append(ref.key)
        name = f"files/new-{len(uploads)}"
        return GeminiFile(
            name=name,
            uri=f"https://generativelanguage.googleapis.com/v1beta/{name}",
            expires_at=datetime.now(UTC) + timedelta(hours=48),
        )

    async def fake_delete(name: str) -> None:
        deleted.append(name)

    async def fake_generate(**kwargs) -> BinaryImage:
        inputs.extend(kwargs["input_media"])
        return BinaryImage(data=_ONE_PIXEL_PNG, media_type="image/png")

    monkeypatch.setattr(media_inputs_tools, "upload_gemini_file", fake_upload)
    monkeypatch.setattr(media_inputs_tools, "delete_gemini_file", fake_delete)
    monkeypatch.setattr(video_to_image_tools, "run_native_image_generation", fake_generate)
    return uploads, inputs, deleted


async def test_gemini_api_video_uploads_once_per_revision(
    db_session_factory, monkeypatch, image_input_storage
):
    uploads, inputs, _deleted = _gemini_api_video(monkeypatch)
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["generate_image_from_video"],
        tool_policies={"generate_image_from_video": "auto"},
    )
    source, earlier = await _video_source(db_session_factory, context)
    await _cache_upload(
        db_session_factory,
        earlier.id,
        name="files/earlier-revision",
        expires_at=datetime.now(UTC) + timedelta(hours=40),
    )
    async with db_session_factory() as db:
        file = await db.get_one(File, source.id)
        current = build_file_revision(file, revision_number=2, created_by_user_id=context.user_id)
        db.add(current)
        await db.flush()
        await get_storage_provider().put_object(
            private_ref_from_key(current.object_key), b"newer-video", content_type="video/mp4"
        )
        file.current_revision_id = current.id
        file.revision_count = 2
        await db.commit()

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[_video_call(source, "first"), _video_call(source, "second"), "Done."]
        ),
    )

    assert result.run.status == "completed"
    # The earlier revision's upload isn't the current video, so it is never reused.
    assert uploads == [current.object_key]
    assert [item.file_id for item in inputs if isinstance(item, UploadedFile)] == [
        "https://generativelanguage.googleapis.com/v1beta/files/new-1"
    ] * 2
    [audit] = [row for row in result.audit_rows if row.details.get("operation")]
    assert audit.details["gemini_file_name"] == "files/new-1"
    assert audit.details["revision_id"] == str(current.id)


async def test_gemini_api_expired_upload_is_replaced(
    db_session_factory, monkeypatch, image_input_storage
):
    uploads, _inputs, deleted = _gemini_api_video(monkeypatch)
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["generate_image_from_video"],
        tool_policies={"generate_image_from_video": "auto"},
    )
    source, revision = await _video_source(db_session_factory, context)
    await _cache_upload(
        db_session_factory,
        revision.id,
        name="files/expiring",
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(turns=[_video_call(source, "expired"), "Done."]),
    )

    assert result.run.status == "completed"
    assert uploads == [revision.object_key]
    assert deleted == ["files/expiring"]
    async with db_session_factory() as db:
        saved = await db.get_one(FileRevision, revision.id)
    assert saved.gemini_file_name == "files/new-1"
