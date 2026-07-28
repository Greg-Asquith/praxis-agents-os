# apps/api/tests/services/agents/runtime/test_file_tools.py

"""Tests for runtime file tools."""

import importlib
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import uuid4

import pytest
from pydantic_ai import (
    Agent as PydanticAgent,
    ApprovalRequired,
    DeferredToolRequests,
    ModelRetry,
    RunContext,
    ToolReturn,
)
from pydantic_ai.messages import (
    BinaryContent,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RunUsage
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from core.settings import settings
from models.agent import Agent
from models.agent_run import AgentRun
from models.conversation import Conversation
from models.files import FileRevision
from models.user import User
from models.workspace import Workspace
from services.agent_runs import create_agent_run
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.envelope import RunEnvelope
from services.agents.runtime.sinks import CollectingSink
from services.agents.runtime.staged_tool_content import (
    WRITE_FILE_CONTENT_REF_ARG,
    resolve_staged_write_content,
    stage_write_file_approval_content,
    tool_args_for_display,
)
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_EFFECT_WRITE,
    TOOL_POLICY_AUTO,
)
from services.agents.runtime.tools.files import (
    list_files as runtime_list_files,
    read_file,
    write_file,
)
from services.agents.runtime.tools.files.utils import slice_text
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.files import write_agent_file
from services.files.contract import FileCategory
from services.files.utils import private_ref_from_key, sha256_hex
from services.storage.factory import get_storage_provider
from tests.factories import build_file, build_file_revision, build_user, build_workspace
from tests.support.storage import reset_storage_provider_cache

pytestmark = pytest.mark.asyncio


@dataclass(frozen=True)
class RuntimeFileTestContext:
    user: User
    workspace: Workspace
    agent: Agent
    conversation: Conversation
    run: AgentRun


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


async def test_file_tool_catalog_policies() -> None:
    assert RUNTIME_TOOL_CATALOG["list_files"].effect == TOOL_EFFECT_READ
    assert RUNTIME_TOOL_CATALOG["read_file"].effect == TOOL_EFFECT_READ
    assert RUNTIME_TOOL_CATALOG["write_file"].effect == TOOL_EFFECT_WRITE
    assert RUNTIME_TOOL_CATALOG["write_file"].effect_scope == "internal"
    assert RUNTIME_TOOL_CATALOG["write_file"].default_policy == TOOL_POLICY_AUTO
    assert "promote_scratch" not in RUNTIME_TOOL_CATALOG
    for tool_name in ("list_files", "read_file", "write_file"):
        assert RUNTIME_TOOL_CATALOG[tool_name].configurable is False
        assert RUNTIME_TOOL_CATALOG[tool_name].auto_mount is True


async def test_stages_write_file_approval_content_without_persisting_body(
    local_storage_settings: None,
) -> None:
    workspace_id = uuid4()
    run_id = uuid4()
    call_id = "approval-call-1"
    call = ToolCallPart(
        tool_name="write_file",
        tool_call_id=call_id,
        args={
            "name": "secret.md",
            "content": "sensitive draft body",
        },
    )

    staged = await stage_write_file_approval_content(
        workspace_id=workspace_id,
        run_id=run_id,
        new_messages=[ModelResponse(parts=[call])],
        all_messages=[ModelResponse(parts=[call])],
        deferred_tool_requests=DeferredToolRequests(approvals=[call]),
    )

    approval = staged.deferred_tool_requests.approvals[0]
    assert isinstance(approval.args, dict)
    assert "content" not in approval.args
    assert WRITE_FILE_CONTENT_REF_ARG in approval.args
    assert (
        "sensitive draft body"
        not in ModelMessagesTypeAdapter.dump_json(staged.all_messages).decode()
    )
    display_args = tool_args_for_display(
        tool_name="write_file",
        args=approval.args,
        metadata=staged.deferred_tool_requests.metadata[call_id],
    )
    assert display_args["content"] == "[staged for approval; content omitted]"
    assert display_args["content_bytes"] == len("sensitive draft body")
    assert (
        await resolve_staged_write_content(
            workspace_id=workspace_id,
            run_id=run_id,
            content_ref=approval.args[WRITE_FILE_CONTENT_REF_ARG],
        )
        == "sensitive draft body"
    )


async def test_rejects_invalid_staged_write_content_ref() -> None:
    workspace_id = uuid4()
    run_id = uuid4()
    valid_name = f"{'a' * 64}-{'b' * 64}.txt"

    for content_ref in (
        f"workspaces/{workspace_id}/agent-runs/{run_id}/staged-tool-inputs/../secret.txt",
        f"workspaces/{workspace_id}/agent-runs/{run_id}/staged-tool-inputs/not-hashes.txt",
        f"workspaces/{uuid4()}/agent-runs/{run_id}/staged-tool-inputs/{valid_name}",
    ):
        with pytest.raises(AppValidationError):
            await resolve_staged_write_content(
                workspace_id=workspace_id,
                run_id=run_id,
                content_ref=content_ref,
            )


async def test_list_files_returns_workspace_files(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    context = await _runtime_file_context(db_session)
    await write_agent_file(
        db_session,
        workspace=context.workspace,
        agent=context.agent,
        name="notes.md",
        content="durable notes",
    )
    output = await runtime_list_files(_run_context(db_session, context))

    assert [file.name for file in output.files] == ["notes.md"]
    assert output.total == 1


async def test_durable_write_requires_approval_and_records_agent_revision(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    context = await _runtime_file_context(db_session)

    with pytest.raises(ApprovalRequired) as exc_info:
        await write_file(
            _run_context(db_session, context),
            name="report",
            content="approved content",
        )

    assert exc_info.value.metadata["name"] == "report"

    output = await write_file(
        _run_context(db_session, context, approved=True),
        name="report",
        content="approved content",
    )

    revision = await db_session.get(FileRevision, output.revision_id)
    assert output.name == "report.md"
    assert revision is not None
    assert revision.created_by_agent_id == context.agent.id
    assert revision.created_by_user_id is None
    assert revision.created_by_system is False
    stored = await get_storage_provider().get_object(private_ref_from_key(revision.object_key))
    assert stored == b"approved content"


async def test_read_file_returns_editable_text_content(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    context = await _runtime_file_context(db_session)
    result = await write_agent_file(
        db_session,
        workspace=context.workspace,
        agent=context.agent,
        name="notes.md",
        content="abcdefghij",
    )

    read_output = await read_file(
        _run_context(db_session, context),
        file_id=result.file.id,
        offset=3,
        max_bytes=4,
    )

    assert read_output["source"] == "content"
    assert read_output["content"] == "defg"
    assert read_output["offset"] == 3
    assert read_output["end_offset"] == 7
    assert read_output["truncated"] is True


async def test_text_slices_preserve_utf8_boundaries() -> None:
    first = slice_text(
        "ab😀cd",
        offset=0,
        max_bytes=4,
        metadata={"kind": "test"},
    )
    second = slice_text(
        "ab😀cd",
        offset=first["end_offset"],
        max_bytes=4,
        metadata={"kind": "test"},
    )
    third = slice_text(
        "ab😀cd",
        offset=second["end_offset"],
        max_bytes=10,
        metadata={"kind": "test"},
    )

    assert first["content"] == "ab"
    assert first["end_offset"] == 2
    assert second["content"] == "😀"
    assert second["end_offset"] == 6
    assert third["content"] == "cd"


async def test_read_file_returns_binary_content_for_images(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    context = await _runtime_file_context(db_session)
    image_file, revision = await _persist_image_file(
        db_session,
        context=context,
        content=b"fake-png",
    )

    read_output = await read_file(_run_context(db_session, context), file_id=image_file.id)

    assert isinstance(read_output, ToolReturn)
    assert read_output.metadata == {
        "file_id": str(image_file.id),
        "revision_id": str(revision.id),
    }
    assert read_output.content is None
    metadata, binary = read_output.return_value
    assert metadata["source"] == "image"
    assert isinstance(binary, BinaryContent)
    assert binary.data == b"fake-png"
    assert binary.media_type == "image/png"


async def test_image_content_reaches_the_post_tool_model_request(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    context = await _runtime_file_context(db_session)
    image_file, _revision = await _persist_image_file(
        db_session,
        context=context,
        content=b"model-visible-png",
    )
    observed_returns: list[ToolReturnPart] = []

    def model_function(messages, _info):
        returns = [
            part
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        if not returns:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_file",
                        args={"file_id": str(image_file.id)},
                        tool_call_id="read-image",
                    )
                ]
            )
        observed_returns.extend(returns)
        return ModelResponse(parts=[TextPart(content="inspected")])

    agent = PydanticAgent(
        FunctionModel(model_function, model_name="image-file-handoff-test"),
        deps_type=RuntimeDeps,
        tools=[read_file],
    )
    result = await agent.run("Inspect the image", deps=_run_context(db_session, context).deps)

    assert result.output == "inspected"
    [tool_return] = observed_returns
    assert tool_return.model_response_object()["source"] == "image"
    [binary] = tool_return.files
    assert isinstance(binary, BinaryContent)
    assert binary.data == b"model-visible-png"
    assert binary.identifier == str(image_file.id)


async def test_ready_document_content_reaches_the_post_tool_model_request(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    context = await _runtime_file_context(db_session)
    document, _revision = await _persist_ready_document(
        db_session,
        context=context,
        markdown=b"# Extracted\n\nThe document is model-visible.",
    )
    observed_returns: list[ToolReturnPart] = []

    def model_function(messages, _info):
        returns = [
            part
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        if not returns:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_file",
                        args={"file_id": str(document.id)},
                        tool_call_id="read-document",
                    )
                ]
            )
        observed_returns.extend(returns)
        return ModelResponse(parts=[TextPart(content="inspected")])

    agent = PydanticAgent(
        FunctionModel(model_function, model_name="document-file-handoff-test"),
        deps_type=RuntimeDeps,
        tools=[read_file],
    )
    result = await agent.run("Inspect the document", deps=_run_context(db_session, context).deps)

    assert result.output == "inspected"
    [tool_return] = observed_returns
    assert tool_return.content["source"] == "markdown"
    assert tool_return.content["content"] == "# Extracted\n\nThe document is model-visible."
    assert "url" not in tool_return.content


async def test_image_content_failure_does_not_present_url_as_inspection(
    db_session: AsyncSession,
    local_storage_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = await _runtime_file_context(db_session)
    image_file, _revision = await _persist_image_file(
        db_session,
        context=context,
        content=b"fake-png",
    )
    read_file_module = importlib.import_module("services.agents.runtime.tools.files.read_file")
    monkeypatch.setattr(read_file_module, "agent_model_supports_vision", lambda _deps: False)

    with pytest.raises(ModelRetry) as exc_info:
        await read_file(_run_context(db_session, context), file_id=image_file.id)

    assert str(exc_info.value) == (
        "The configured model does not support image inspection. "
        "Use mode='url' only if the user requested a download; a URL will not let this model "
        "inspect the image."
    )


async def test_unsupported_content_failure_reserves_url_for_download(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    context = await _runtime_file_context(db_session)
    file, _revision = await _persist_image_file(
        db_session,
        context=context,
        content=b"audio-like-content",
    )
    file.category = FileCategory.AUDIO.value
    await db_session.flush()

    with pytest.raises(ModelRetry) as exc_info:
        await read_file(_run_context(db_session, context), file_id=file.id)

    assert str(exc_info.value) == (
        "This file type cannot be inspected as content. "
        "Use mode='url' only if the user requested a download."
    )


async def test_explicit_url_mode_returns_download_only(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    context = await _runtime_file_context(db_session)
    image_file, _revision = await _persist_image_file(
        db_session,
        context=context,
        content=b"fake-png",
    )

    output = await read_file(
        _run_context(db_session, context),
        file_id=image_file.id,
        mode="url",
    )

    assert output["mode"] == "url"
    assert output["file_id"] == str(image_file.id)
    assert output["category"] == "image"
    assert output["media_type"] == "image/png"
    assert output["processing_status"] == "ready"
    assert output["url"].startswith("http://testserver/")
    assert output["note"] == (
        "Share this link with the user only when they need direct download access; it expires."
    )


async def test_read_file_hides_unknown_file(db_session: AsyncSession) -> None:
    context = await _runtime_file_context(db_session)

    with pytest.raises(ModelRetry, match="File not found"):
        await read_file(
            _run_context(db_session, context),
            file_id=uuid4(),
        )


async def _runtime_file_context(db: AsyncSession) -> RuntimeFileTestContext:
    user = build_user(email=f"runtime-files-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"runtime-files-{uuid4().hex[:8]}")
    db.add_all([user, workspace])
    await db.flush()

    agent = Agent(
        name="Runtime File Agent",
        slug=f"runtime-file-agent-{uuid4().hex[:8]}",
        instructions="Use file tools.",
        workspace_id=workspace.id,
        created_by=user.id,
        model_provider="openai",
        model="gpt-5.4-mini",
        tool_names=[],
    )
    db.add(agent)
    await db.flush()

    conversation = Conversation(
        user_id=user.id,
        workspace_id=workspace.id,
        created_by=user.id,
        active_agent_id=agent.id,
    )
    db.add(conversation)
    await db.flush()

    run = await create_agent_run(
        db,
        conversation_id=conversation.id,
        agent_id=agent.id,
        workspace_id=workspace.id,
        user_id=user.id,
        trigger="interactive",
    )
    return RuntimeFileTestContext(
        user=user,
        workspace=workspace,
        agent=agent,
        conversation=conversation,
        run=run,
    )


def _run_context(
    db: AsyncSession,
    context: RuntimeFileTestContext,
    *,
    approved: bool = False,
) -> RunContext[RuntimeDeps]:
    return RunContext(
        deps=RuntimeDeps(
            db=db,
            user=context.user,
            workspace=context.workspace,
            conversation=context.conversation,
            agent=context.agent,
            run=context.run,
            sink=CollectingSink(run_id=context.run.id, conversation_id=context.conversation.id),
            envelope=RunEnvelope(principal="interactive"),
        ),
        model=FunctionModel(_unused_model_function, model_name="runtime-file-tool-test"),
        usage=RunUsage(),
        tool_call_approved=approved,
    )


def _unused_model_function(_messages, _info) -> ModelResponse:
    return ModelResponse(parts=[TextPart(content="unused")])


async def _persist_image_file(
    db: AsyncSession,
    *,
    context: RuntimeFileTestContext,
    content: bytes,
):
    content_hash = sha256_hex(content)
    file = build_file(
        workspace=context.workspace,
        name="image.png",
        category=FileCategory.IMAGE.value,
        content_type="image/png",
        extension=".png",
        size_bytes=len(content),
        content_hash=content_hash,
    )
    db.add(file)
    await db.flush()

    revision = build_file_revision(
        file,
        created_by_agent_id=context.agent.id,
        size_bytes=len(content),
        content_hash=content_hash,
    )
    await get_storage_provider().put_object(
        private_ref_from_key(revision.object_key),
        content,
        content_type="image/png",
    )
    db.add(revision)
    await db.flush()

    file.current_revision_id = revision.id
    file.revision_count = 1
    await db.flush()
    return file, revision


async def _persist_ready_document(
    db: AsyncSession,
    *,
    context: RuntimeFileTestContext,
    markdown: bytes,
):
    file = build_file(
        workspace=context.workspace,
        name="brief.pdf",
        size_bytes=10,
        content_hash=sha256_hex(b"source-pdf"),
        processing_status="ready",
    )
    db.add(file)
    await db.flush()

    revision = build_file_revision(
        file,
        created_by_agent_id=context.agent.id,
        size_bytes=10,
        content_hash=file.content_hash,
    )
    revision.markdown_object_key = f"{revision.object_key}.extracted.md"
    revision.markdown_size_bytes = len(markdown)
    await get_storage_provider().put_object(
        private_ref_from_key(revision.markdown_object_key),
        markdown,
        content_type="text/markdown",
    )
    db.add(revision)
    await db.flush()

    file.current_revision_id = revision.id
    file.revision_count = 1
    await db.flush()
    return file, revision
