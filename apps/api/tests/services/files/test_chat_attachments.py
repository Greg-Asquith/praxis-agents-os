"""Tests for chat attachment file validation and content assembly."""

import asyncio
import importlib
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import set_session_tenant_context
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
from utils.document_markdown import TRUNCATION_MARKER, DocumentConversionError

pytestmark = pytest.mark.asyncio

FIXTURES_DIR = Path(__file__).parents[2] / "fixtures" / "files"


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

    monkeypatch.setattr(settings, "MAX_MULTIMODAL_DOCUMENT_BYTES", 4)
    monkeypatch.setattr(settings, "MAX_FILE_SIZE_DOCUMENT", 20)
    assert await resolve_chat_attachments(
        db_session,
        workspace_id=workspace.id,
        agent=agent,
        file_ids=[pptx.id],
    ) == [pptx]

    pptx.size_bytes = 21
    await db_session.flush()
    with pytest.raises(AppValidationError, match="Document attachment is too large") as exc_info:
        await resolve_chat_attachments(
            db_session,
            workspace_id=workspace.id,
            agent=agent,
            file_ids=[pptx.id],
        )
    assert exc_info.value.details["max_size_bytes"] == 20

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
    await set_session_tenant_context(
        db_session,
        workspace_id=workspace.id,
        user_id=actor.id,
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


async def test_resolve_chat_attachments_accepts_text_and_office_files_for_claude(
    db_session: AsyncSession,
    local_storage_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor, workspace, agent = await _persist_workspace_agent(db_session)
    agent.model_provider = "anthropic"
    agent.model = "claude-sonnet-4-6"
    monkeypatch.setattr(settings, "MAX_CHAT_ATTACHMENTS", 20)
    file_specs = [
        (
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "slides.pptx",
        ),
        ("application/vnd.ms-powerpoint", "slides.ppt"),
        ("application/msword", "brief.doc"),
        ("application/vnd.ms-excel", "budget.xls"),
        (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "brief.docx",
        ),
        (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "budget.xlsx",
        ),
        ("text/csv", "budget.csv"),
        ("text/html", "brief.html"),
        ("text/markdown", "brief.md"),
        ("application/json", "brief.json"),
    ]
    files = [
        (
            await _persist_file(
                db_session,
                workspace=workspace,
                actor=actor,
                content_type=content_type,
                filename=filename,
            )
        )[0]
        for content_type, filename in file_specs
    ]

    resolved = await resolve_chat_attachments(
        db_session,
        workspace_id=workspace.id,
        agent=agent,
        file_ids=[file.id for file in files],
    )

    assert resolved == files


async def test_resolve_chat_attachments_rejects_video(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    actor, workspace, agent = await _persist_workspace_agent(db_session)
    video, _revision = await _persist_file(
        db_session,
        workspace=workspace,
        actor=actor,
        content_type="video/mp4",
        filename="clip.mp4",
    )

    with pytest.raises(AppValidationError, match="File type cannot be attached"):
        await resolve_chat_attachments(
            db_session,
            workspace_id=workspace.id,
            agent=agent,
            file_ids=[video.id],
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
            model_type="standard",
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


async def test_build_attachment_user_content_converts_text_and_keeps_image_raw(
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
    assert [content.media_type for content in contents] == ["text/plain", "image/png"]
    html_payload = contents[0].data.decode()
    assert f"File id: {html.id}" in html_payload
    assert "Original format: HTML (text/html), 14 bytes" in html_payload
    assert "# Hello" in html_payload
    assert contents[1].data == b"png"


async def test_build_attachment_user_content_uses_stored_powerpoint_markdown(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    actor, workspace, _agent = await _persist_workspace_agent(db_session)
    powerpoint, revision = await _persist_file(
        db_session,
        workspace=workspace,
        actor=actor,
        content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename="board-deck.pptx",
        content=b"not a valid PowerPoint",
    )
    revision.markdown_object_key = f"{revision.object_key}.extracted.md"
    await get_storage_provider().put_object(
        private_ref_from_key(revision.markdown_object_key),
        b"# Stored board update",
        content_type="text/markdown",
    )
    await db_session.flush()

    [content] = await build_attachment_user_content(db_session, files=[powerpoint])

    payload = content.data.decode()
    assert content.identifier == str(powerpoint.id)
    assert content.media_type == "text/plain"
    assert "Original format: PowerPoint" in payload
    assert "# Stored board update" in payload


async def test_build_attachment_user_content_converts_powerpoint_on_demand(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    actor, workspace, _agent = await _persist_workspace_agent(db_session)
    powerpoint, _revision = await _persist_file(
        db_session,
        workspace=workspace,
        actor=actor,
        content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename="sample.pptx",
        content=(FIXTURES_DIR / "sample.pptx").read_bytes(),
    )

    [content] = await build_attachment_user_content(db_session, files=[powerpoint])

    assert content.identifier == str(powerpoint.id)
    assert content.media_type == "text/plain"
    assert "Deck Title Slide" in content.data.decode()


async def test_build_attachment_user_content_keeps_pdf_raw(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    actor, workspace, _agent = await _persist_workspace_agent(db_session)
    pdf, _revision = await _persist_file(
        db_session,
        workspace=workspace,
        actor=actor,
        content_type="application/pdf",
        filename="brief.pdf",
        content=b"pdf",
    )

    [content] = await build_attachment_user_content(db_session, files=[pdf])

    assert content.identifier == str(pdf.id)
    assert content.media_type == "application/pdf"
    assert content.data == b"pdf"


async def test_build_attachment_user_content_maps_conversion_timeout(
    db_session: AsyncSession,
    local_storage_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder_module = importlib.import_module("services.files.build_attachment_user_content")
    actor, workspace, _agent = await _persist_workspace_agent(db_session)
    powerpoint, _revision = await _persist_file(
        db_session,
        workspace=workspace,
        actor=actor,
        content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename="slides.pptx",
    )

    async def conversion_that_does_not_finish(*_args, **_kwargs) -> str:
        await asyncio.Future()

    monkeypatch.setattr(builder_module, "markdown_for_revision", conversion_that_does_not_finish)
    monkeypatch.setattr(settings, "CHAT_ATTACHMENT_CONVERSION_TIMEOUT_SECONDS", 0.001)

    with pytest.raises(AppValidationError, match="couldn't be read") as exc_info:
        await build_attachment_user_content(db_session, files=[powerpoint])

    assert exc_info.value.field == "attachments"
    assert exc_info.value.details == {
        "file_id": str(powerpoint.id),
        "content_type": powerpoint.content_type,
    }


async def test_build_attachment_user_content_maps_conversion_error(
    db_session: AsyncSession,
    local_storage_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder_module = importlib.import_module("services.files.build_attachment_user_content")
    actor, workspace, _agent = await _persist_workspace_agent(db_session)
    document, _revision = await _persist_file(
        db_session,
        workspace=workspace,
        actor=actor,
        content_type="application/msword",
        filename="brief.doc",
    )

    async def failed_conversion(*_args, **_kwargs) -> str:
        raise DocumentConversionError("conversion failed")

    monkeypatch.setattr(builder_module, "markdown_for_revision", failed_conversion)

    with pytest.raises(AppValidationError, match="couldn't be read") as exc_info:
        await build_attachment_user_content(db_session, files=[document])

    assert exc_info.value.details["file_id"] == str(document.id)


async def test_build_attachment_user_content_truncates_stored_markdown(
    db_session: AsyncSession,
    local_storage_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor, workspace, _agent = await _persist_workspace_agent(db_session)
    text, revision = await _persist_file(
        db_session,
        workspace=workspace,
        actor=actor,
        content_type="text/markdown",
        filename="notes.md",
    )
    revision.markdown_object_key = f"{revision.object_key}.extracted.md"
    await get_storage_provider().put_object(
        private_ref_from_key(revision.markdown_object_key),
        b"x" * 200,
        content_type="text/markdown",
    )
    await db_session.flush()
    monkeypatch.setattr(settings, "FILES_MAX_MARKDOWN_BYTES", 100)

    [content] = await build_attachment_user_content(db_session, files=[text])

    assert TRUNCATION_MARKER in content.data.decode()


async def test_build_attachment_user_content_propagates_storage_errors(
    db_session: AsyncSession,
    local_storage_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder_module = importlib.import_module("services.files.build_attachment_user_content")

    actor, workspace, _agent = await _persist_workspace_agent(db_session)
    image, _image_revision = await _persist_file(
        db_session,
        workspace=workspace,
        actor=actor,
        content_type="image/png",
        filename="screen.png",
        content=b"hello",
    )

    class BrokenStorage:
        async def get_object(self, _ref):
            raise RuntimeError("storage unavailable")

    monkeypatch.setattr(builder_module, "get_storage_provider", lambda: BrokenStorage())

    with pytest.raises(RuntimeError, match="storage unavailable"):
        await build_attachment_user_content(db_session, files=[image])


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
