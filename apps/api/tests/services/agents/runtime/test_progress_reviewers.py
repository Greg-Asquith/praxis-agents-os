# apps/api/tests/services/agents/runtime/test_progress_reviewers.py

"""What progress reviews send to reviewer models and accept back."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx2 as httpx
import pytest
from pydantic import SecretStr
from pydantic_ai.models import override_allow_model_requests

from core.settings import settings
from services.agents.models import factory, resolve_progress_review_model
from services.agents.models.utils import _build_retrying_http_client
from services.agents.runtime.progress_review import decisions, review
from services.agents.runtime.progress_review.digest import ProgressDigest
from services.agents.runtime.progress_review.verdict import VERDICT_DESCRIPTIONS
from tests.support.anthropic import anthropic_message_response

DIGEST = ProgressDigest(text="## Run\nTask: Summarise spend.", signal=None)


def _deps():
    return SimpleNamespace(
        **{name: SimpleNamespace(id=uuid4()) for name in ("workspace", "agent", "user", "run")},
        conversation=SimpleNamespace(id=uuid4()),
    )


def _decision(answer: dict) -> dict:
    return {
        "model": "gpt-6-luna",
        "answers": [answer],
        "usage": {
            "input_tokens": 1200,
            "input_tokens_details": {"cached_tokens": 1000, "cache_write_tokens": 0},
            "output_tokens": 0,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 1200,
        },
    }


@pytest.mark.parametrize(
    ("answer", "verdict", "reason"),
    [
        (
            {"type": "choice", "name": "verdict", "choice": "steer_wrap_up", "confidence": 0.9},
            "steer_wrap_up",
            VERDICT_DESCRIPTIONS["steer_wrap_up"],
        ),
        (
            {"type": "choice", "name": "verdict", "choice": "continue", "confidence": 0.4},
            "ask_person",
            decisions.LOW_CONFIDENCE_REASON,
        ),
        ({"type": "refusal", "name": "verdict"}, "ask_person", decisions.REFUSED_REASON),
    ],
)
async def test_decisions_request_and_answer_mapping(monkeypatch, answer, verdict, reason):
    monkeypatch.setattr(settings, "AGENT_RUN_PROGRESS_REVIEW_PROVIDER", "openai")
    # Decisions serves gpt-6-luna only, so another OpenAI model falls back to it.
    monkeypatch.setattr(settings, "AGENT_RUN_PROGRESS_REVIEW_MODEL", "gpt-6.1-sol")
    meter = AsyncMock()
    monkeypatch.setattr("services.ai_usage.run_metered_helper.record_ai_usage_durable", meter)
    requests = []
    if answer["type"] == "choice":
        rest = (1 - answer["confidence"]) / (len(VERDICT_DESCRIPTIONS) - 1)
        probabilities = [
            {
                "value": value,
                "probability": answer["confidence"] if value == answer["choice"] else rest,
            }
            for value in VERDICT_DESCRIPTIONS
        ]
        body = {**answer, "probabilities": probabilities}
    else:
        body = answer

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=_decision(body))

    async with _build_retrying_http_client(httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(factory, "retrying_http_client", lambda: client)
        with override_allow_model_requests(True):
            result = await review.review_progress(_deps(), DIGEST)

    assert (result.verdict, result.reason) == (verdict, reason)
    assert (result.provider, result.model) == ("openai", "gpt-6-luna")
    [request] = requests
    assert request.url.path == "/v1/decisions"
    sent = json.loads(request.content)
    assert (sent["model"], sent["input"]) == ("gpt-6-luna", DIGEST.text)
    assert sent["prompt_cache_options"] == {"mode": "explicit"}
    [question] = sent["questions"]
    assert question["type"] == "choice"
    assert [choice["value"] for choice in question["choices"]] == list(VERDICT_DESCRIPTIONS)
    event = meter.call_args.args[0]
    assert (event.purpose, event.requests, event.input_tokens, event.cache_read_tokens) == (
        "run_review",
        1,
        1200,
        1000,
    )


async def test_gemini_decisions_request_and_answer_mapping(monkeypatch):
    monkeypatch.setattr(settings, "AGENT_RUN_PROGRESS_REVIEW_PROVIDER", "google")
    monkeypatch.setattr(settings, "AGENT_RUN_PROGRESS_REVIEW_MODEL", "gemini-3.8-flash")
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", SecretStr("test-key"))
    meter = AsyncMock()
    monkeypatch.setattr("services.ai_usage.run_metered_helper.record_ai_usage_durable", meter)
    requests = []

    def respond(request):
        requests.append(request)
        probabilities = dict.fromkeys(VERDICT_DESCRIPTIONS, 0.025)
        probabilities["steer_refocus"] = 0.9
        return httpx.Response(
            200,
            json={
                "answers": {
                    "q0": {
                        "type": "choice",
                        "choice": "steer_refocus",
                        "confidence": 0.9,
                        "probabilities": probabilities,
                    }
                },
                "usage": {
                    "total_input_tokens": 900,
                    "input_tokens_by_modality": [{"modality": "TEXT", "tokens": 900}],
                    "total_output_tokens": 0,
                    "total_tokens": 900,
                },
            },
        )

    async with _build_retrying_http_client(httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(factory, "retrying_http_client", lambda: client)
        with override_allow_model_requests(True):
            result = await review.review_progress(_deps(), DIGEST)

    assert (result.verdict, result.reason) == (
        "steer_refocus",
        VERDICT_DESCRIPTIONS["steer_refocus"],
    )
    assert (result.provider, result.model) == ("google", "gemini-decision-1")
    [request] = requests
    assert request.url.path == "/v1beta/decisions"
    sent = json.loads(request.content)
    assert (sent["model"], sent["input"]) == ("gemini-decision-1", DIGEST.text)
    [question] = sent["questions"].values()
    assert question["type"] == "choice"
    assert list(question["criteria"]) == list(VERDICT_DESCRIPTIONS)
    event = meter.call_args.args[0]
    assert (event.provider, event.model, event.input_tokens) == ("google", "gemini-decision-1", 900)


def test_google_reviewer_on_vertex_uses_structured_output(monkeypatch):
    # Gemini Decisions isn't on Vertex, so a Vertex-only deployment keeps its configured model.
    monkeypatch.setattr(settings, "AGENT_RUN_PROGRESS_REVIEW_PROVIDER", "google")
    monkeypatch.setattr(settings, "AGENT_RUN_PROGRESS_REVIEW_MODEL", "gemini-3.8-flash")
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", True)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", "test-project")

    assert resolve_progress_review_model().model == "gemini-3.8-flash"


async def test_structured_reviewer_returns_a_bounded_verdict_without_caching(monkeypatch):
    monkeypatch.setattr(settings, "AGENT_PROMPT_CACHE_ENABLED", True)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr("test-key"))
    meter = AsyncMock()
    monkeypatch.setattr("services.ai_usage.run_metered_helper.record_ai_usage_durable", meter)
    output = {
        "verdict": "steer_stop_repeating",
        "reason": "It keeps running the same search.",
        "guidance": "Try   the\nother account.",
    }
    message = {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-5-5",
        "content": [{"type": "text", "text": json.dumps(output)}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return anthropic_message_response(request, message)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(factory, "retrying_http_client", lambda: client)
        with override_allow_model_requests(True):
            result = await review.review_progress(_deps(), DIGEST)

    [sent] = requests
    assert sent["messages"][-1]["content"][-1]["text"] == DIGEST.text
    # The agent default turns caching on; a unique digest would only pay for the write.
    assert "cache_control" not in json.dumps(sent)
    assert result.verdict == "steer_stop_repeating"
    assert result.guidance == "Try the other account."
    assert (result.provider, result.model) == ("anthropic", "claude-haiku-5-5")
    assert meter.call_args.args[0].purpose == "run_review"
