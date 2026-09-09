"""Governed native image-generation scenarios through the production runtime."""

import base64
import json
from collections.abc import Iterator

import httpx2 as httpx
import pytest
from pydantic import SecretStr
from pydantic_ai import DeferredToolResults, ModelRetry, ToolApproved
from pydantic_ai.messages import BinaryImage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.settings import settings
from models.ai_usage_event import AIUsageEvent
from models.audit_event import AuditEvent
from models.files import File, FileReference, FileRevision
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.tools.native import image_generation as image_generation_tools
from services.files.utils import private_ref_from_key
from services.storage.factory import get_storage_provider
from tests.support.openai_images import image_request, mock_openai_images
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
def image_storage(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
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


@pytest.mark.parametrize("provider", ["google", "openai"])
async def test_generate_image_approval_resumes_with_edited_prompt(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    image_storage: None,
    provider: str,
    openai_image_requests,
) -> None:
    _enable_google(monkeypatch)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("sk-openai-test"))
    generated_prompts: list[str] = []

    async def fake_generate(*, deps, prompt: str, aspect_ratio, model_spec) -> BinaryImage:
        assert deps.db.in_transaction() is False
        generated_prompts.append(prompt)
        assert aspect_ratio == "3:2"
        assert model_spec.model == "gemini-3.1-flash-image"
        return BinaryImage(data=_ONE_PIXEL_PNG, media_type="image/png")

    if provider == "google":
        monkeypatch.setattr(image_generation_tools, "run_native_image_generation", fake_generate)
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["generate_image"],
        tool_policies={"generate_image": "approval"},
    )
    model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        "generate_image",
                        {
                            "prompt": "A blue fox",
                            "model_provider": provider,
                            "aspect_ratio": "3:2",
                        },
                        "image-approval",
                    ),
                )
            ),
            "The approved image was generated and saved.",
        ]
    )

    suspended = await run_scenario(db_session_factory, context, model=model)

    assert suspended.run.status == RUN_STATUS_AWAITING_APPROVAL
    state = load_suspended_run_state(suspended.run)
    assert "A blue fox" in json.dumps(state.message_history, default=str)
    assert generated_prompts == []
    assert openai_image_requests == []

    resumed = await run_scenario(
        db_session_factory,
        context,
        model=model,
        prompt=None,
        expected_status=RUN_STATUS_AWAITING_APPROVAL,
        message_history=state.message_history,
        deferred_tool_results=DeferredToolResults(
            approvals={
                state.pending_tool_call_ids[0]: ToolApproved(
                    override_args={
                        "prompt": "A red fox",
                        "aspect_ratio": "3:2",
                        "model_provider": provider,
                        "model": None,
                    }
                )
            }
        ),
    )

    assert resumed.run.status == "completed"
    if provider == "google":
        assert generated_prompts == ["A red fox"]
    else:
        [request] = openai_image_requests
        assert image_request(request)["prompt"] == "A red fox"
    assert resumed.output == "The approved image was generated and saved."
    tool_audits = [row for row in resumed.audit_rows if row.tool_name == "generate_image"]
    assert {row.details["outcome"] for row in tool_audits} == {
        "approval_requested",
        "completed",
    }


@pytest.mark.parametrize(
    ("provider", "image_model"),
    [("google", "gemini-3.1-flash-image"), ("openai", "gpt-image-2.5-flare")],
)
async def test_generate_image_auto_policy_persists_workspace_scoped_file(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    image_storage: None,
    provider: str,
    image_model: str,
    openai_image_requests,
) -> None:
    _enable_google(monkeypatch)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("sk-openai-test"))

    async def fake_generate(*, deps, prompt: str, aspect_ratio, model_spec) -> BinaryImage:
        del deps
        assert prompt == "A paper-cut mountain at sunrise"
        assert aspect_ratio is None
        assert model_spec.provider == provider
        return BinaryImage(data=_ONE_PIXEL_PNG, media_type="image/png")

    if provider == "google":
        monkeypatch.setattr(image_generation_tools, "run_native_image_generation", fake_generate)
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["generate_image"],
        tool_policies={"generate_image": "auto"},
    )
    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn(
                    (
                        ToolCall(
                            "generate_image",
                            {
                                "prompt": "  A paper-cut mountain at sunrise  ",
                                "model_provider": provider,
                            },
                            "auto-image",
                        ),
                    )
                ),
                "The image is ready in workspace Files.",
            ]
        ),
    )

    assert result.run.status == "completed"
    [returned] = result.tool_returns("generate_image")
    assert returned["content"]["image_model"] == image_model
    assert returned["content"]["model"] == image_model
    if provider == "openai":
        [request] = openai_image_requests
        assert image_request(request)["prompt"] == "  A paper-cut mountain at sunrise  "
    async with db_session_factory() as db:
        if provider == "openai":
            [usage] = (
                await db.scalars(
                    select(AIUsageEvent).where(
                        AIUsageEvent.run_id == context.run_id,
                        AIUsageEvent.purpose == "image_generation",
                    )
                )
            ).all()
            assert (usage.model, usage.input_tokens, usage.output_tokens, usage.requests) == (
                image_model,
                10,
                20,
                1,
            )
        file = await db.scalar(
            select(File).where(
                File.workspace_id == context.workspace_id,
                File.content_type == "image/png",
            )
        )
        assert file is not None
        revision = await db.get(FileRevision, file.current_revision_id)
        assert revision is not None
        assert revision.created_by_agent_id == context.agent_id
        stored = await get_storage_provider().get_object(private_ref_from_key(revision.object_key))
        assert stored == _ONE_PIXEL_PNG
        audit = await db.scalar(
            select(AuditEvent).where(
                AuditEvent.workspace_id == context.workspace_id,
                AuditEvent.resource_type == "file",
                AuditEvent.resource_id == str(file.id),
            )
        )
        assert audit is not None
        assert audit.details["source"] == "native_image_generation"
        assert await db.scalar(
            select(FileReference.id).where(
                FileReference.file_id == file.id,
                FileReference.target_type == "conversation",
                FileReference.target_id == context.conversation_id,
            )
        )


async def test_generate_image_is_hidden_without_google_or_openai(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr("sk-ant-test"))
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", None)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", False)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)
    context = await build_scenario_agent(db_session_factory, tool_names=["generate_image"])
    seen_requests = []

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=["Image generation is not configured."],
            seen_requests=seen_requests,
        ),
    )

    assert result.run.status == "completed"
    assert "generate_image" not in {tool.name for tool in seen_requests[0][1].function_tools}


async def test_generate_image_policy_refusal_is_model_visible_and_audited(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_google(monkeypatch)

    async def fake_generate(*, deps, prompt: str, aspect_ratio, model_spec) -> BinaryImage:
        del deps, prompt, aspect_ratio, model_spec
        raise ModelRetry(
            "The image provider declined this prompt under its content policy. "
            "Revise the prompt and try again."
        )

    monkeypatch.setattr(image_generation_tools, "run_native_image_generation", fake_generate)
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["generate_image"],
        tool_policies={"generate_image": "auto"},
    )
    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn(
                    (
                        ToolCall(
                            "generate_image",
                            {
                                "prompt": "A disallowed image request",
                                "model_provider": "google",
                            },
                            "refused-image",
                        ),
                    )
                ),
                "The provider declined that prompt under its content policy.",
            ]
        ),
    )

    assert result.run.status == "completed"
    assert result.output == "The provider declined that prompt under its content policy."
    [audit] = [row for row in result.audit_rows if row.tool_name == "generate_image"]
    assert audit.status == "failure"
    assert audit.details["outcome"] == "failed"
    assert audit.details["error_code"] == "ToolRetryError"


@pytest.mark.parametrize("refused", [False, True])
async def test_direct_image_provider_failure_is_contained_and_audited(
    db_session_factory, monkeypatch, image_storage, refused
):
    _enable_google(monkeypatch)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("sk-openai-test"))
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["generate_image"],
        tool_policies={"generate_image": "auto"},
    )

    def respond(_request):
        return httpx.Response(
            400 if refused else 403,
            json={
                "error": {
                    "code": "moderation_blocked" if refused else "access_denied",
                    "message": "private provider detail",
                }
            },
        )

    async with mock_openai_images(monkeypatch, respond) as requests:
        result = await run_scenario(
            db_session_factory,
            context,
            model=scripted_model(
                turns=[
                    ToolTurn(
                        (
                            ToolCall(
                                "generate_image",
                                {
                                    "prompt": "A fox",
                                    "model_provider": "openai",
                                },
                                "failed-image",
                            ),
                        )
                    ),
                    "The image could not be generated.",
                ]
            ),
        )
    assert len(requests) == 1
    assert result.run.status == "completed"
    [audit] = [row for row in result.audit_rows if row.tool_name == "generate_image"]
    assert audit.status == "failure"
    assert "private provider detail" not in json.dumps(audit.details)
    async with db_session_factory() as db:
        assert (
            await db.scalar(select(File.id).where(File.workspace_id == context.workspace_id))
            is None
        )
        [usage] = (
            await db.scalars(
                select(AIUsageEvent).where(
                    AIUsageEvent.run_id == context.run_id,
                    AIUsageEvent.purpose == "image_generation",
                )
            )
        ).all()
        assert usage.model == "gpt-image-2.5-flare"
        assert usage.requests == 1
