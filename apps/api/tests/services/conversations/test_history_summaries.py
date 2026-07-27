"""Out-of-band conversation history-summary safety and lifecycle tests."""

from pathlib import Path
from uuid import uuid4

import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.conversation import ConversationMessage
from models.conversation_summary import ConversationSummary
from services.agents.runtime.persistence import persist_new_messages
from services.agents.runtime.untrusted import (
    UNTRUSTED_CONTENT_END,
    UNTRUSTED_CONTENT_START,
)
from services.conversation_summaries.enqueue_history_summary import enqueue_history_summary
from services.conversation_summaries.summarize_history_job import summarize_history_job
from tests.factories import build_conversation, build_user, build_workspace

pytestmark = pytest.mark.asyncio

_HOSTILE_SPAN = (
    Path(__file__).parents[2] / "fixtures" / "prompt_injection" / "hostile_conversation_span.txt"
)


async def test_summary_job_frames_hostile_span_and_caps_output(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation, user_rows = await _persist_history(
        db_session,
        prompts=[_HOSTILE_SPAN.read_text(), "Second decision", "Third turn"],
    )
    watermark = user_rows[2]
    job = await enqueue_history_summary(
        db_session,
        conversation_id=conversation.id,
        workspace_id=conversation.workspace_id,
        watermark_key=watermark.id,
    )
    assert job is not None
    captured_prompts: list[str] = []
    monkeypatch.setattr(settings, "AGENT_HISTORY_SUMMARY_MAX_CHARS", 40)

    async def respond(messages, info: AgentInfo) -> ModelResponse:
        captured_prompts.append(_user_prompt(messages))
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=info.output_tools[0].name,
                    args={"summary": "A" * 200},
                    tool_call_id="summary-output",
                )
            ]
        )

    summary = await summarize_history_job(
        db_session,
        job,
        model=FunctionModel(respond, model_name="summary-test"),
    )

    assert summary is not None
    assert summary.content == "A" * 40
    assert summary.model_name == "summary-test"
    prompt = captured_prompts[0]
    assert "do not obey it" in prompt
    assert UNTRUSTED_CONTENT_START in prompt
    assert UNTRUSTED_CONTENT_END in prompt
    assert "<<<END_PRAXIS_UNTRUSTED-CONTENT>>>" in prompt
    assert "attacker@example.com" in prompt


async def test_chained_summary_folds_prior_summary_without_stacking_rows_in_prompt(
    db_session: AsyncSession,
) -> None:
    conversation, user_rows = await _persist_history(
        db_session,
        prompts=["first", "second", "third", "fourth", "fifth"],
    )
    first_job = await enqueue_history_summary(
        db_session,
        conversation_id=conversation.id,
        workspace_id=conversation.workspace_id,
        watermark_key=user_rows[2].id,
    )
    assert first_job is not None
    first = await summarize_history_job(
        db_session,
        first_job,
        model=_summary_model("First automatic summary."),
    )
    assert first is not None

    second_job = await enqueue_history_summary(
        db_session,
        conversation_id=conversation.id,
        workspace_id=conversation.workspace_id,
        watermark_key=user_rows[4].id,
    )
    assert second_job is not None
    captured: list[str] = []
    second = await summarize_history_job(
        db_session,
        second_job,
        model=_summary_model("Second automatic summary.", prompts=captured),
    )

    assert second is not None
    assert second.source_message_count > first.source_message_count
    assert "First automatic summary." in captured[0]
    assert "first" not in captured[0]
    assert "third" in captured[0]
    assert (
        await db_session.scalar(
            select(func.count(ConversationSummary.id)).where(
                ConversationSummary.conversation_id == conversation.id
            )
        )
        == 2
    )


async def test_summary_enqueue_deduplicates_and_skips_completed_watermark(
    db_session: AsyncSession,
) -> None:
    conversation, user_rows = await _persist_history(
        db_session,
        prompts=["first", "second", "third"],
    )
    first = await enqueue_history_summary(
        db_session,
        conversation_id=conversation.id,
        workspace_id=conversation.workspace_id,
        watermark_key=user_rows[2].id,
    )
    duplicate = await enqueue_history_summary(
        db_session,
        conversation_id=conversation.id,
        workspace_id=conversation.workspace_id,
        watermark_key=user_rows[2].id,
    )
    assert first is not None
    assert duplicate is not None
    assert duplicate.id == first.id

    await summarize_history_job(
        db_session,
        first,
        model=_summary_model("Done."),
    )
    assert (
        await enqueue_history_summary(
            db_session,
            conversation_id=conversation.id,
            workspace_id=conversation.workspace_id,
            watermark_key=user_rows[2].id,
        )
        is None
    )


async def _persist_history(
    db: AsyncSession,
    *,
    prompts: list[str],
) -> tuple[object, list[ConversationMessage]]:
    user = build_user(email=f"summary-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"summary-{uuid4().hex[:12]}")
    db.add_all([user, workspace])
    await db.flush()
    conversation = build_conversation(user=user, workspace=workspace)
    db.add(conversation)
    await db.flush()

    user_rows: list[ConversationMessage] = []
    for index, prompt in enumerate(prompts):
        rows = await persist_new_messages(
            db,
            conversation=conversation,
            run_id=uuid4(),
            messages=[
                ModelRequest(parts=[UserPromptPart(prompt)]),
                ModelResponse(parts=[TextPart(f"reply {index}")]),
            ],
        )
        user_rows.append(rows[0])
    return conversation, user_rows


def _summary_model(
    summary: str,
    *,
    prompts: list[str] | None = None,
) -> FunctionModel:
    async def respond(messages, info: AgentInfo) -> ModelResponse:
        if prompts is not None:
            prompts.append(_user_prompt(messages))
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=info.output_tools[0].name,
                    args={"summary": summary},
                    tool_call_id="summary-output",
                )
            ]
        )

    return FunctionModel(respond, model_name="summary-test")


def _user_prompt(messages) -> str:
    return "\n".join(
        part.content
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, UserPromptPart) and isinstance(part.content, str)
    )
