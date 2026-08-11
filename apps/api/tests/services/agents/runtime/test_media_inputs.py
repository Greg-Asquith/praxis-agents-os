"""Tests for provider-neutral governed workspace media loading."""

from dataclasses import dataclass
from hashlib import sha256
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.workspace import Workspace
from services.agents.runtime.entity_references.domain import FileReference
from services.agents.runtime.tools import media_inputs as media_inputs_tools
from services.agents.runtime.tools.media_inputs import (
    load_workspace_media_input,
    load_workspace_media_inputs,
)
from services.files.contract import FileCategory
from services.files.utils import private_ref_from_key
from services.storage.factory import get_storage_provider
from tests.factories import build_file, build_file_revision, build_workspace
from tests.support.storage import reset_storage_provider_cache


@dataclass(frozen=True)
class _Deps:
    db: AsyncSession
    workspace: Workspace


@dataclass(frozen=True)
class _Context:
    deps: _Deps


@pytest.fixture
def media_storage(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    reset_storage_provider_cache()
    try:
        yield
    finally:
        reset_storage_provider_cache()


async def _persist_media(
    db: AsyncSession,
    *,
    workspace: Workspace,
    name: str,
    category: FileCategory,
    content_type: str,
    extension: str,
    content: bytes,
):
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
    await db.flush()
    return file, revision


async def test_media_inputs_preserve_reference_order_and_current_revision(
    db_session: AsyncSession,
    media_storage: None,
) -> None:
    workspace = build_workspace(slug=f"media-inputs-{uuid4().hex[:8]}")
    db_session.add(workspace)
    await db_session.flush()
    first, first_revision = await _persist_media(
        db_session,
        workspace=workspace,
        name="first.png",
        category=FileCategory.IMAGE,
        content_type="image/png",
        extension=".png",
        content=b"first-image",
    )
    second, second_revision = await _persist_media(
        db_session,
        workspace=workspace,
        name="second.jpg",
        category=FileCategory.IMAGE,
        content_type="image/jpeg",
        extension=".jpg",
        content=b"second-image",
    )

    loaded = await load_workspace_media_inputs(
        _Context(_Deps(db_session, workspace)),  # type: ignore[arg-type]
        [
            FileReference(entity_id=second.id, label=second.name),
            FileReference(entity_id=first.id, label=first.name),
        ],
        category=FileCategory.IMAGE,
        allowed_media_types={"image/jpeg", "image/png"},
        tool_name="edit_image",
        kind_label="image",
        max_total_bytes=len(b"second-image") + len(b"first-image"),
    )

    assert [item.file_id for item in loaded] == [second.id, first.id]
    assert [item.revision_id for item in loaded] == [second_revision.id, first_revision.id]
    assert [item.content.data for item in loaded] == [b"second-image", b"first-image"]


async def test_media_inputs_reject_aggregate_size_before_loading_objects(
    db_session: AsyncSession,
    media_storage: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = build_workspace(slug=f"aggregate-media-{uuid4().hex[:8]}")
    db_session.add(workspace)
    await db_session.flush()
    references: list[FileReference] = []
    for name in ("first.png", "second.png"):
        file, _revision = await _persist_media(
            db_session,
            workspace=workspace,
            name=name,
            category=FileCategory.IMAGE,
            content_type="image/png",
            extension=".png",
            content=b"12345",
        )
        references.append(FileReference(entity_id=file.id, label=file.name))

    class _UnexpectedStorageRead:
        async def get_object(self, _ref):
            raise AssertionError("aggregate metadata should be checked before object loading")

    monkeypatch.setattr(
        media_inputs_tools,
        "get_storage_provider",
        lambda: _UnexpectedStorageRead(),
    )

    with pytest.raises(ModelRetry, match="files totaling at most 9 bytes"):
        await load_workspace_media_inputs(
            _Context(_Deps(db_session, workspace)),  # type: ignore[arg-type]
            references,
            category=FileCategory.IMAGE,
            allowed_media_types={"image/png"},
            tool_name="edit_image",
            kind_label="image",
            max_total_bytes=9,
        )


async def test_media_input_rejects_wrong_category(
    db_session: AsyncSession,
    media_storage: None,
) -> None:
    workspace = build_workspace(slug=f"wrong-media-{uuid4().hex[:8]}")
    db_session.add(workspace)
    await db_session.flush()
    video, _revision = await _persist_media(
        db_session,
        workspace=workspace,
        name="clip.mp4",
        category=FileCategory.VIDEO,
        content_type="video/mp4",
        extension=".mp4",
        content=b"video",
    )

    with pytest.raises(ModelRetry, match="requires an image file"):
        await load_workspace_media_input(
            _Context(_Deps(db_session, workspace)),  # type: ignore[arg-type]
            FileReference(entity_id=video.id, label=video.name),
            category=FileCategory.IMAGE,
            allowed_media_types={"image/png"},
            tool_name="edit_image",
            kind_label="image",
        )


async def test_media_input_normalizes_mime_and_enforces_byte_bound(
    db_session: AsyncSession,
    media_storage: None,
) -> None:
    workspace = build_workspace(slug=f"video-media-{uuid4().hex[:8]}")
    db_session.add(workspace)
    await db_session.flush()
    video, _revision = await _persist_media(
        db_session,
        workspace=workspace,
        name="clip.mov",
        category=FileCategory.VIDEO,
        content_type="video/mov",
        extension=".mov",
        content=b"12345",
    )
    reference = FileReference(entity_id=video.id, label=video.name)

    loaded = await load_workspace_media_input(
        _Context(_Deps(db_session, workspace)),  # type: ignore[arg-type]
        reference,
        category=FileCategory.VIDEO,
        allowed_media_types={"video/mov", "video/mp4"},
        tool_name="generate_image_from_video",
        kind_label="video",
        max_bytes=5,
        media_type_overrides={"video/mov": "video/quicktime"},
    )

    assert loaded.content.media_type == "video/quicktime"
    with pytest.raises(ModelRetry, match="too large"):
        await load_workspace_media_input(
            _Context(_Deps(db_session, workspace)),  # type: ignore[arg-type]
            reference,
            category=FileCategory.VIDEO,
            allowed_media_types={"video/mov", "video/mp4"},
            tool_name="generate_image_from_video",
            kind_label="video",
            max_bytes=4,
            media_type_overrides={"video/mov": "video/quicktime"},
        )


async def test_media_input_hides_cross_workspace_file(
    db_session: AsyncSession,
    media_storage: None,
) -> None:
    active_workspace = build_workspace(slug=f"active-media-{uuid4().hex[:8]}")
    other_workspace = build_workspace(slug=f"other-media-{uuid4().hex[:8]}")
    db_session.add_all([active_workspace, other_workspace])
    await db_session.flush()
    other_file, _revision = await _persist_media(
        db_session,
        workspace=other_workspace,
        name="private.png",
        category=FileCategory.IMAGE,
        content_type="image/png",
        extension=".png",
        content=b"private-image",
    )

    with pytest.raises(ModelRetry, match="File not found"):
        await load_workspace_media_input(
            _Context(_Deps(db_session, active_workspace)),  # type: ignore[arg-type]
            FileReference(entity_id=other_file.id, label=other_file.name),
            category=FileCategory.IMAGE,
            allowed_media_types={"image/png"},
            tool_name="edit_image",
            kind_label="image",
        )
