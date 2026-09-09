"""Provider rate limits retain the same safe failure in storage and the stream."""

import httpx2 as httpx
import pytest
from pydantic import SecretStr
from pydantic_ai import models
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.function import FunctionModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.database import set_session_tenant_context
from core.settings import settings
from models.agent_run import AgentRun
from services.agents.models import factory
from services.agents.models.domain import ResolvedModel
from services.agents.runtime.sinks import CollectingSink
from tests.support.scenario import build_scenario_agent, run_scenario


async def test_rate_limit_persists_and_emits_safe_error(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def fail_request(_messages, _info):
        yield "Starting"
        raise ModelHTTPError(429, "test-model", {"message": "private project quota detail"})

    context = await build_scenario_agent(committed_db_session_factory)
    sink = CollectingSink(run_id=context.run_id, conversation_id=context.conversation_id)
    with pytest.raises(ModelHTTPError):
        await run_scenario(
            committed_db_session_factory,
            context,
            model=FunctionModel(stream_function=fail_request),
            sink=sink,
        )

    async with committed_db_session_factory() as db:
        await set_session_tenant_context(db, workspace_id=context.workspace_id)
        run = await db.get(AgentRun, context.run_id)
        assert run is not None
        assert run.status == "failed"
        assert run.error_code == "model_rate_limited"
        error = next(event for event in sink.events if event.event == "error")
        assert error.data["code"] == run.error_code
        assert error.data["message"] == run.error_message
        assert "Try again later" in run.error_message
        assert "private" not in run.error_message
    assert sink.events[-1].event == "done"
    assert sink.events[-1].data["status"] == "failed"


async def test_azure_filtered_stream_settles_safely_without_retry(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch,
) -> None:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", True)
    monkeypatch.setattr(settings, "AZURE_OPENAI_API_KEY", SecretStr("test-key"))
    monkeypatch.setattr(settings, "AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            400,
            json={
                "error": {
                    "code": "content_filter",
                    "message": "private provider moderation detail",
                }
            },
        )

    context = await build_scenario_agent(committed_db_session_factory)
    sink = CollectingSink(run_id=context.run_id, conversation_id=context.conversation_id)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(factory, "retrying_http_client", lambda: client)
        model = factory.build_model(
            ResolvedModel(
                provider="azure",
                model="gpt-5.4-mini",
                transport_model="gpt-5.4-mini",
                azure_deployment="test-deployment",
                settings={},
                max_steps=3,
            )
        )
        # The SDK streaming adapter mishandles its filtered ModelResponse.
        with pytest.raises(TypeError, match=r"ModelResponse.*asynchronous context manager"):
            await run_scenario(committed_db_session_factory, context, model=model, sink=sink)

    assert len(requests) == 1
    async with committed_db_session_factory() as db:
        await set_session_tenant_context(db, workspace_id=context.workspace_id)
        run = await db.get(AgentRun, context.run_id)
        assert run.status == "failed"
        assert run.error_code == "agent_run_failed"
        assert run.error_message == "The agent run failed unexpectedly."
        error = next(event for event in sink.events if event.event == "error")
        assert error.data["message"] == run.error_message
        assert error.data["code"] == run.error_code
    assert not any(event.event in {"tool.call", "tool.result"} for event in sink.events)
    assert sink.events[-1].event == "done"
    assert sink.events[-1].data["status"] == "failed"
