"""Platform File reads retain tenant attachment pins and withdrawal boundaries."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry
from sqlalchemy import select

from core.database import maintenance_async_db_session, set_session_tenant_context
from core.exceptions.general import NotFoundError
from core.settings import settings
from models.agent import Agent
from models.files import File, FileReference
from services.agents.runtime.entity_references.domain import FileReference as RuntimeFileReference
from services.agents.runtime.entity_references.internal import _resolve_files, _search_files
from services.agents.runtime.load_context import load_available_files
from services.agents.runtime.tools.files.list_files import list_files
from services.agents.runtime.tools.files.read_file import read_file
from services.agents.runtime.tools.native.run_code_file_bridge import (
    load_run_code_inputs,
    resolve_run_code_edit_target,
)
from services.files import (
    build_attachment_user_content,
    create_conversation_file_references,
    resolve_chat_attachments,
)
from services.files.utils import file_revision_ref, sha256_hex
from services.storage.factory import get_storage_provider
from tests.factories import (
    build_conversation,
    build_file,
    build_file_revision,
    build_user,
    build_workspace,
)
from tests.support.storage import reset_storage_provider_cache
from utils.content import ContentScope

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def platform_runtime(db_session_factory, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "APP_BASE_URL", "http://testserver")
    reset_storage_provider_cache()
    async with maintenance_async_db_session() as db:
        user, workspace, other_workspace = (
            build_user(email=f"platform-runtime-{uuid4().hex}@example.com"),
            build_workspace(slug=f"runtime-a-{uuid4().hex[:8]}"),
            build_workspace(slug=f"runtime-b-{uuid4().hex[:8]}"),
        )
        agent = Agent(
            name="File reader",
            slug=f"file-reader-{uuid4().hex[:8]}",
            workspace_id=workspace.id,
            created_by=user.id,
            instructions="Read files.",
            model_provider="openai",
            model="gpt-5.4-mini",
        )
        conversation = build_conversation(user=user, workspace=workspace)
        db.add_all([user, workspace, other_workspace, agent, conversation])
        await db.flush()
        file = build_file(
            workspace=workspace,
            workspace_id=None,
            scope=ContentScope.PLATFORM,
            name="template.txt",
            content_type="text/plain",
            extension=".txt",
            category="editable_text",
            size_bytes=3,
            content_hash=sha256_hex(b"old"),
        )
        db.add(file)
        await db.flush()
        revision = await _revision(db, file, b"old", number=1)
        file.current_revision_id = file.published_revision_id = revision.id
        file.is_published = True
        file.revision_count = 1
    try:
        yield SimpleNamespace(
            user=user,
            workspace=workspace,
            other_workspace=other_workspace,
            agent=agent,
            conversation=conversation,
            file=file,
            revision=revision,
        )
    finally:
        reset_storage_provider_cache()


async def _revision(db, file, content, *, number):
    revision = build_file_revision(
        file,
        is_published=True,
        revision_number=number,
        revision_kind="create" if number == 1 else "edit",
        size_bytes=len(content),
        content_hash=sha256_hex(content),
    )
    await get_storage_provider().put_object(
        file_revision_ref(revision), content, content_type="text/plain"
    )
    db.add(revision)
    await db.flush()
    return revision


def _ctx(db, context):
    return SimpleNamespace(
        deps=SimpleNamespace(
            db=db,
            workspace=context.workspace,
            conversation=context.conversation,
            agent=context.agent,
        )
    )


async def _attach(db, context):
    await set_session_tenant_context(db, workspace_id=context.workspace.id, user_id=context.user.id)
    await create_conversation_file_references(
        db,
        workspace_id=context.workspace.id,
        conversation_id=context.conversation.id,
        file_ids=[context.file.id],
        created_by_user_id=context.user.id,
    )
    await db.commit()


async def test_platform_attachment_pin_survives_publication_in_prompt_tools_and_code(
    db_session,
    platform_runtime,
):
    context = platform_runtime
    await _attach(db_session, context)
    async with maintenance_async_db_session() as db:
        file = await db.get(File, context.file.id)
        replacement = await _revision(db, file, b"replacement", number=2)
        file.current_revision_id = file.published_revision_id = replacement.id
        file.size_bytes = replacement.size_bytes
        file.revision_count = 2
    await set_session_tenant_context(
        db_session, workspace_id=context.workspace.id, user_id=context.user.id
    )
    # Reattaching preserves the original reference instead of advancing its pin.
    await create_conversation_file_references(
        db_session,
        workspace_id=context.workspace.id,
        conversation_id=context.conversation.id,
        file_ids=[context.file.id],
        created_by_user_id=context.user.id,
    )
    reference = await db_session.scalar(
        select(FileReference).where(FileReference.file_id == context.file.id)
    )
    assert reference.file_revision_id == context.revision.id
    files = await resolve_chat_attachments(
        db_session,
        workspace_id=context.workspace.id,
        agent=context.agent,
        conversation_id=context.conversation.id,
        file_ids=[context.file.id],
    )
    assert files[0].current_revision_id == context.revision.id
    [content] = await build_attachment_user_content(db_session, files=files)
    assert content.data.endswith(b"old")
    [available] = await load_available_files(db_session, context.conversation)
    assert available.size_bytes == 3
    ctx = _ctx(db_session, context)
    ref = RuntimeFileReference(entity_id=context.file.id, label=context.file.name)
    assert (await read_file(ctx, ref))["content"] == "old"
    [code_input] = await load_run_code_inputs(ctx, [ref])
    assert code_input.content == b"old"
    assert code_input.revision_id == context.revision.id
    with pytest.raises(ModelRetry, match="workspace copy"):
        resolve_run_code_edit_target([code_input], updates_file_id=ref, provider="openai")
    [unpinned] = await resolve_chat_attachments(
        db_session,
        workspace_id=context.workspace.id,
        agent=context.agent,
        file_ids=[context.file.id],
    )
    assert unpinned.current_revision_id == replacement.id
    assert (await list_files(ctx)).files[0].size_bytes == len(b"replacement")


async def test_platform_reference_is_private_to_requesting_workspace(db_session, platform_runtime):
    context = platform_runtime
    await _attach(db_session, context)
    await set_session_tenant_context(
        db_session, workspace_id=context.other_workspace.id, user_id=context.user.id
    )
    assert (
        await db_session.scalar(
            select(FileReference).where(FileReference.file_id == context.file.id)
        )
        is None
    )
    foreign_conversation = SimpleNamespace(
        id=context.conversation.id, workspace_id=context.other_workspace.id
    )
    assert await load_available_files(db_session, foreign_conversation) == []
    [visible] = await resolve_chat_attachments(
        db_session,
        workspace_id=context.other_workspace.id,
        agent=context.agent,
        file_ids=[context.file.id],
    )
    assert visible.id == context.file.id


async def test_platform_withdrawal_hides_attachments_search_and_tools(db_session, platform_runtime):
    context = platform_runtime
    await _attach(db_session, context)
    async with maintenance_async_db_session() as db:
        file = await db.get(File, context.file.id)
        file.is_published = False
    await set_session_tenant_context(
        db_session, workspace_id=context.workspace.id, user_id=context.user.id
    )
    assert await load_available_files(db_session, context.conversation) == []
    with pytest.raises(NotFoundError):
        await resolve_chat_attachments(
            db_session,
            workspace_id=context.workspace.id,
            agent=context.agent,
            file_ids=[context.file.id],
            conversation_id=context.conversation.id,
        )
    ctx = _ctx(db_session, context)
    ref = RuntimeFileReference(entity_id=context.file.id, label=context.file.name)
    assert (await list_files(ctx)).total == 0
    with pytest.raises(ModelRetry, match="not found"):
        await read_file(ctx, ref)
    with pytest.raises(ModelRetry, match="not found"):
        await load_run_code_inputs(ctx, [ref])
    entity_ctx = SimpleNamespace(db=db_session, workspace=context.workspace)
    assert not (await _search_files(entity_ctx, "template", {}, 25, None)).choices
    assert await _resolve_files(entity_ctx, [ref], {}) == ()
