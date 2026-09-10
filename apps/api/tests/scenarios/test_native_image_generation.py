"""Governed native image-generation scenarios through the production runtime."""

import asyncio
import base64
import json
from collections.abc import Iterator
from uuid import uuid4

import httpx2 as httpx
import pytest
from pydantic import SecretStr
from pydantic_ai import DeferredToolResults, ModelRetry, ToolApproved, ToolDenied
from pydantic_ai.messages import BinaryImage
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.settings import settings
from models.ai_usage_event import AIUsageEvent
from models.audit_event import AuditEvent
from models.files import File, FileReference, FileRevision
from models.workspace import WorkspaceMembership, WorkspaceRole
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.tools.native import image_generation as image_generation_tools
from services.files.utils import private_ref_from_key
from services.storage.factory import get_storage_provider
from tests.support.google_native import google_image_response, mock_google_native
from tests.support.openai_images import image_request, image_response, mock_openai_images
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


async def test_vertex_image_approval_uses_real_adapter_and_persists_once(
    db_session_factory, monkeypatch, image_storage
):
    from tests.support.google_native import mock_google_native

    _enable_google(monkeypatch)
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", None)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", "image-test")
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_LOCATION", "auto")
    async with mock_google_native(monkeypatch, vertex=True) as requests:
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
                                "prompt": "A fox",
                                "model_provider": "google",
                            },
                            "vertex-image",
                        ),
                    )
                ),
                "The image was saved.",
            ]
        )
        suspended = await run_scenario(db_session_factory, context, model=model)
        state = load_suspended_run_state(suspended.run)
        assert requests == []
        resumed = await run_scenario(
            db_session_factory,
            context,
            model=model,
            prompt=None,
            expected_status=RUN_STATUS_AWAITING_APPROVAL,
            message_history=state.message_history,
            deferred_tool_results=DeferredToolResults(
                approvals={
                    state.pending_tool_call_ids[0]: ToolApproved(),
                }
            ),
        )
    assert resumed.run.status == "completed"
    [request] = requests
    assert request.url.host == "aiplatform.eu.rep.googleapis.com"
    assert "/projects/image-test/locations/eu/" in request.url.path
    assert request.headers["authorization"] == "Bearer test-adc"
    async with db_session_factory() as db:
        files = (
            await db.scalars(
                select(File).where(
                    File.workspace_id == context.workspace_id,
                )
            )
        ).all()
        assert len(files) == 1
        [usage] = (
            await db.scalars(
                select(AIUsageEvent).where(
                    AIUsageEvent.run_id == context.run_id,
                    AIUsageEvent.purpose == "image_generation",
                )
            )
        ).all()
        assert (usage.requests, usage.input_tokens, usage.output_tokens) == (1, 10, 20)


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


@pytest.mark.parametrize("verdict", ["denied", "revoked"])
async def test_image_approval_rejection_makes_no_provider_request(
    db_session_factory, monkeypatch, image_storage, verdict
):
    _enable_google(monkeypatch)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("sk-openai-test"))
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
                        {"prompt": "A fox", "model_provider": "openai"},
                        "image-approval",
                    ),
                )
            ),
            "No image was generated.",
        ]
    )
    async with mock_openai_images(monkeypatch) as requests:
        suspended = await run_scenario(db_session_factory, context, model=model)
        state = load_suspended_run_state(suspended.run)
        if verdict == "revoked":
            async with db_session_factory() as db:
                await db.execute(
                    update(WorkspaceMembership)
                    .where(
                        WorkspaceMembership.workspace_id == context.workspace_id,
                        WorkspaceMembership.user_id == context.user_id,
                    )
                    .values(role=WorkspaceRole.READ_ONLY)
                )
                await db.commit()
        resumed = await run_scenario(
            db_session_factory,
            context,
            model=model,
            prompt=None,
            expected_status=RUN_STATUS_AWAITING_APPROVAL,
            message_history=state.message_history,
            deferred_tool_results=DeferredToolResults(
                approvals={
                    state.pending_tool_call_ids[0]: ToolDenied("Declined")
                    if verdict == "denied"
                    else ToolApproved()
                }
            ),
        )
    assert requests == []
    assert not any(
        row.details.get("outcome") == "completed"
        for row in resumed.audit_rows
        if row.tool_name == "generate_image"
    )
    async with db_session_factory() as db:
        assert (
            await db.scalar(select(File.id).where(File.workspace_id == context.workspace_id))
            is None
        )
        assert (
            await db.scalar(
                select(AIUsageEvent.id).where(
                    AIUsageEvent.run_id == context.run_id,
                    AIUsageEvent.purpose == "image_generation",
                )
            )
            is None
        )


@pytest.mark.parametrize(
    "failure", ["empty", "multiple", "malformed", "oversize", "storage", "missing_reference"]
)
async def test_image_failures_publish_no_successful_reference(
    db_session_factory, monkeypatch, image_storage, failure
):
    _enable_google(monkeypatch)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("sk-openai-test"))
    tool = "edit_image" if failure == "missing_reference" else "generate_image"
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=[tool],
        tool_policies={tool: "auto"},
    )
    body = image_response()
    if failure == "empty":
        body["data"] = []
    elif failure == "multiple":
        body["data"] *= 2
    elif failure == "malformed":
        body["data"] = [{"b64_json": "invalid base64"}]
    elif failure == "oversize":
        monkeypatch.setattr(settings, "MAX_FILE_SIZE_IMAGE", 1)
    elif failure == "storage":

        async def fail_storage(*args, **kwargs):
            raise OSError("Storage unavailable")

        monkeypatch.setattr(get_storage_provider(), "put_object", fail_storage)
    args = {"prompt": "A fox", "model_provider": "openai"}
    if failure == "missing_reference":
        args["file_ids"] = [str(uuid4())]
    async with mock_openai_images(
        monkeypatch, lambda _: httpx.Response(200, json=body)
    ) as requests:

        async def run():
            return await run_scenario(
                db_session_factory,
                context,
                model=scripted_model(
                    turns=[
                        ToolTurn((ToolCall(tool, args, "image-failure"),)),
                        "No image was saved.",
                    ]
                ),
            )

        if failure == "storage":
            with pytest.raises(OSError, match="Storage unavailable"):
                await run()
        else:
            result = await run()
            assert not any(
                row.details.get("outcome") == "completed"
                for row in result.audit_rows
                if row.tool_name == tool
            )
    assert len(requests) == (0 if failure == "missing_reference" else 1)
    async with db_session_factory() as db:
        assert (
            await db.scalar(
                select(FileReference.id).where(FileReference.workspace_id == context.workspace_id)
            )
            is None
        )
        usage = (
            await db.scalars(
                select(AIUsageEvent).where(
                    AIUsageEvent.run_id == context.run_id,
                    AIUsageEvent.purpose == "image_generation",
                )
            )
        ).all()
        if failure == "missing_reference":
            assert usage == []
        else:
            [event] = usage
            assert (event.requests, event.input_tokens, event.output_tokens) == (1, 10, 20)


@pytest.mark.parametrize("vertex", [False, True])
@pytest.mark.parametrize(
    "failure",
    [
        "rejection",
        "rate_limit",
        "timeout",
        "malformed",
        "malformed_json",
        "invalid_base64",
        "refusal",
        "storage",
        "cancellation",
    ],
)
async def test_google_image_failure_preserves_outcome_and_usage(
    db_session_factory, monkeypatch, image_storage, failure, vertex
):
    _enable_google(monkeypatch)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", "test-project")
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_LOCATION", "global")
    monkeypatch.setattr(settings, "LLM_HTTP_RETRY_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(settings, "LLM_HTTP_RETRY_MAX_WAIT_SECONDS", 0.01)
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["generate_image"],
        tool_policies={"generate_image": "auto"},
    )
    body = google_image_response()
    if failure == "malformed":
        body["candidates"][0]["content"]["parts"] = [{"text": "No image"}]
    elif failure == "invalid_base64":
        body["candidates"][0]["content"]["parts"][0]["inlineData"]["data"] = "invalid base64"
    elif failure == "refusal":
        body["candidates"][0]["content"]["parts"] = []
        body["candidates"][0]["finishReason"] = "SAFETY"
    elif failure == "storage":

        async def fail_storage(*args, **kwargs):
            raise OSError("Storage unavailable")

        monkeypatch.setattr(get_storage_provider(), "put_object", fail_storage)

    def respond(request):
        if failure == "malformed_json":
            return httpx.Response(
                200, text="{private provider detail", headers={"content-type": "application/json"}
            )
        if failure == "timeout":
            raise httpx.ReadTimeout("private provider detail", request=request)
        if failure == "cancellation":
            raise asyncio.CancelledError()
        if failure in {"rejection", "rate_limit"}:
            code = 403 if failure == "rejection" else 429
            return httpx.Response(
                code,
                json={
                    "error": {
                        "code": code,
                        "message": "private provider detail",
                        "status": "PERMISSION_DENIED" if code == 403 else "RESOURCE_EXHAUSTED",
                    }
                },
            )
        return httpx.Response(200, json=body)

    async with mock_google_native(monkeypatch, respond, vertex=vertex) as requests:

        async def run():
            return await run_scenario(
                db_session_factory,
                context,
                model=scripted_model(
                    turns=[
                        ToolTurn(
                            (
                                ToolCall(
                                    "generate_image",
                                    {"prompt": "A fox", "model_provider": "google"},
                                    "google-image-failure",
                                ),
                            )
                        ),
                        "No image was saved.",
                    ]
                ),
            )

        if failure in {"storage", "cancellation"}:
            with pytest.raises(OSError if failure == "storage" else asyncio.CancelledError):
                await run()
        else:
            result = await run()
            assert result.run.status == "completed"
            [audit] = [row for row in result.audit_rows if row.tool_name == "generate_image"]
            assert audit.status == "failure"
            assert audit.details["outcome"] == "failed"
            assert "private provider detail" not in json.dumps(audit.details)
            history = json.dumps([message.parts for message in result.messages])
            assert "private provider detail" not in history
            if failure == "refusal":
                assert "Revise the prompt and try again" in history
            elif failure == "invalid_base64":
                assert "The image provider could not complete the request" in history
    assert len(requests) == (2 if failure in {"rate_limit", "timeout"} else 1)
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
        assert usage.model == "gemini-3.1-flash-image"
        assert usage.requests == 1
        if failure in {"storage", "malformed", "refusal"}:
            assert (usage.input_tokens, usage.output_tokens) == (10, 20)
        else:
            # Invalid wire responses expose no parsed usage through the SDK.
            assert (usage.input_tokens, usage.output_tokens) == (0, 0)
