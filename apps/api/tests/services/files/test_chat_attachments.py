"""Tests for chat attachment file validation and content assembly."""

import importlib
from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, NotFoundError
from core.settings import settings
from models.agent import Agent
from services.agents.models.domain import ModelInfo
from services.files import build_attachment_user_content, resolve_chat_attachments
from services.files.contract import contract_for_content_type
from services.files.utils import private_ref_from_key, revision_object_key, sha256_hex
from services.storage.factory import get_storage_provider
from tests.factories import build_file, build_file_revision, build_user, build_workspace
from tests.support.storage import reset_storage_provider_cache

pytestmark = pytest.mark.asyncio


@pytest.fixture
def local_storage_settings(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "APP_BASE_URL", "http://testserver")
    reset_storage_provider_cache()
    try:
        yield
    finally:
        reset_storage_provider_cache()


async def test_resolve_chat_attachments_preserves_order_and_dedupes(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    actor, workspace, agent = await _persist_workspace_agent(db_session)
    pdf, _pdf_revision = await _persist_file(
        db_session,
        workspace=workspace,
        actor=actor,
        content_type="application/pdf",
        filename="brief.pdf",
    )
    image, _image_revision = await _persist_file(
        db_session,
        workspace=workspace,
        actor=actor,
        content_type="image/png",
        filename="screen.png",
    )
    html, _html_revision = await _persist_file(
        db_session,
        workspace=workspace,
        actor=actor,
        content_type="text/html",
        filename="page.html",
    )

    resolved = await resolve_chat_attachments(
        db_session,
        workspace_id=workspace.id,
        agent=agent,
        file_ids=[pdf.id, image.id, pdf.id, html.id],
    )

    assert [file.id for file in resolved] == [pdf.id, image.id, html.id]


async def test_resolve_chat_attachments_rejects_count_size_type_and_scope(
    db_session: AsyncSession,
    local_storage_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor, workspace, agent = await _persist_workspace_agent(db_session)
    text, _text_revision = await _persist_file(
        db_session,
        workspace=workspace,
        actor=actor,
        content_type="text/plain",
        content=b"hello",
    )
    pdf, _pdf_revision = await _persist_file(
        db_session,
        workspace=workspace,
        actor=actor,
        content_type="application/pdf",
        filename="large.pdf",
        content=b"large",
    )
    pptx, _pptx_revision = await _persist_file(
        db_session,
        workspace=workspace,
        actor=actor,
        content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename="slides.pptx",
        content=b"slides",
    )

    monkeypatch.setattr(settings, "MAX_CHAT_ATTACHMENTS", 1)
    with pytest.raises(AppValidationError, match="Too many chat attachments"):
        await resolve_chat_attachments(
            db_session,
            workspace_id=workspace.id,
            agent=agent,
            file_ids=[text.id, pdf.id],
        )

    monkeypatch.setattr(settings, "MAX_CHAT_ATTACHMENTS", 5)
    monkeypatch.setattr(settings, "MAX_MULTIMODAL_DOCUMENT_BYTES", 4)
    with pytest.raises(AppValidationError, match="Document attachment is too large"):
        await resolve_chat_attachments(
            db_session,
            workspace_id=workspace.id,
            agent=agent,
            file_ids=[pdf.id],
        )

    monkeypatch.setattr(settings, "MAX_MULTIMODAL_DOCUMENT_BYTES", 20)
    with pytest.raises(AppValidationError, match="Document type is not supported"):
        await resolve_chat_attachments(
            db_session,
            workspace_id=workspace.id,
            agent=agent,
            file_ids=[pptx.id],
        )

    foreign_workspace = build_workspace(slug=f"foreign-{uuid4().hex[:8]}")
    db_session.add(foreign_workspace)
    await db_session.flush()
    foreign_file, _foreign_revision = await _persist_file(
        db_session,
        workspace=foreign_workspace,
        actor=actor,
        content_type="text/plain",
        filename="foreign.txt",
        content=b"foreign",
    )
    with pytest.raises(NotFoundError):
        await resolve_chat_attachments(
            db_session,
            workspace_id=workspace.id,
            agent=agent,
            file_ids=[foreign_file.id],
        )

    text.deleted = True
    await db_session.flush()
    with pytest.raises(NotFoundError):
        await resolve_chat_attachments(
            db_session,
            workspace_id=workspace.id,
            agent=agent,
            file_ids=[text.id],
        )


async def test_resolve_chat_attachments_rejects_images_for_non_vision_models(
    db_session: AsyncSession,
    local_storage_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver_module = importlib.import_module("services.files.resolve_chat_attachments")

    actor, workspace, agent = await _persist_workspace_agent(db_session)
    image, _image_revision = await _persist_file(
        db_session,
        workspace=workspace,
        actor=actor,
        content_type="image/png",
        filename="screen.png",
        content=b"png",
    )
    monkeypatch.setattr(
        resolver_module,
        "get_model",
        lambda _provider, _model: ModelInfo(
            provider="test",
            model="no-vision",
            display_name="No Vision",
            context_window=1000,
            supports_vision=False,
        ),
    )

    with pytest.raises(AppValidationError, match="No Vision"):
        await resolve_chat_attachments(
            db_session,
            workspace_id=workspace.id,
            agent=agent,
            file_ids=[image.id],
        )


async def test_build_attachment_user_content_reads_current_revision_blobs(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    actor, workspace, _agent = await _persist_workspace_agent(db_session)
    html, _html_revision = await _persist_file(
        db_session,
        workspace=workspace,
        actor=actor,
        content_type="text/html",
        filename="page.html",
        content=b"<h1>Hello</h1>",
    )
    image, _image_revision = await _persist_file(
        db_session,
        workspace=workspace,
        actor=actor,
        content_type="image/png",
        filename="screen.png",
        content=b"png",
    )

    contents = await build_attachment_user_content(db_session, files=[html, image])

    assert [content.identifier for content in contents] == [str(html.id), str(image.id)]
    assert [content.media_type for content in contents] == ["text/html", "image/png"]
    assert [content.data for content in contents] == [b"<h1>Hello</h1>", b"png"]


async def test_build_attachment_user_content_propagates_storage_errors(
    db_session: AsyncSession,
    local_storage_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder_module = importlib.import_module("services.files.build_attachment_user_content")

    actor, workspace, _agent = await _persist_workspace_agent(db_session)
    text, _text_revision = await _persist_file(
        db_session,
        workspace=workspace,
        actor=actor,
        content_type="text/plain",
        filename="notes.txt",
        content=b"hello",
    )

    class BrokenStorage:
        async def get_object(self, _ref):
            raise RuntimeError("storage unavailable")

    monkeypatch.setattr(builder_module, "get_storage_provider", lambda: BrokenStorage())

    with pytest.raises(RuntimeError, match="storage unavailable"):
        await build_attachment_user_content(db_session, files=[text])


async def _persist_workspace_agent(db: AsyncSession):
    actor = build_user(email=f"chat-files-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"chat-files-{uuid4().hex[:8]}")
    agent = Agent(
        name="Vision Agent",
        slug=f"vision-agent-{uuid4().hex[:8]}",
        instructions="Describe inputs.",
        workspace_id=workspace.id,
        created_by=actor.id,
        model_provider="openai",
        model="gpt-5.4-mini",
    )
    db.add_all([actor, workspace, agent])
    await db.flush()
    return actor, workspace, agent


async def _persist_file(
    db: AsyncSession,
    *,
    workspace,
    actor,
    content_type: str,
    filename: str = "example.txt",
    content: bytes = b"hello",
):
    entry = contract_for_content_type(content_type)
    content_hash = sha256_hex(content)
    file = build_file(
        workspace=workspace,
        name=filename,
        category=entry.category.value,
        content_type=entry.content_type,
        extension=entry.extensions[0],
        size_bytes=len(content),
        content_hash=content_hash,
    )
    db.add(file)
    await db.flush()
    revision_id = uuid4()
    object_key = revision_object_key(workspace.id, file.id, revision_id, entry.extensions[0])
    await get_storage_provider().put_object(
        private_ref_from_key(object_key),
        content,
        content_type=entry.content_type,
    )
    revision = build_file_revision(
        file,
        revision_id=revision_id,
        created_by_user_id=actor.id,
        object_key=object_key,
        size_bytes=len(content),
        content_hash=content_hash,
    )
    db.add(revision)
    await db.flush()
    file.current_revision_id = revision.id
    file.revision_count = 1
    await db.flush()
    return file, revision
