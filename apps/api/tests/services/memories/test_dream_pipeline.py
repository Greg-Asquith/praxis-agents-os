# apps/api/tests/services/memories/test_dream_pipeline.py

"""A dream from schedule to applied memories, with a scripted helper model."""

import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import set_session_tenant_context
from core.settings import settings
from models.agent_memories import AgentMemory
from models.agent_run import AgentRun
from models.jobs import Job
from models.memory_dream_run import MemoryDreamRun
from services.agents.runtime.persistence import persist_new_messages
from services.agents.runtime.untrusted import UNTRUSTED_CONTENT_END, UNTRUSTED_CONTENT_START
from services.conversation_review import render_transcript
from services.memories.dream import advance_dream_run, schedule_dreams
from tests.factories.conversations import build_conversation
from tests.factories.users import build_user
from tests.factories.workspaces import build_workspace, build_workspace_membership
from tests.services.memories.conftest import MemoryContext, install_fake_embeddings

_FIXTURES = Path(__file__).parents[2] / "fixtures" / "prompt_injection"
_CANDIDATE = re.compile(r'\{"conversation": "(k\d+)", "title": "([^"]+)", "content_md": "([^"]+)"')


@pytest.fixture(autouse=True)
def _dreaming_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MEMORY_DREAM_ENABLED", True)
    # Usage rows commit on the test's one connection, which can't take concurrent savepoints.
    monkeypatch.setattr(
        sys.modules["services.memories.dream.advance_dream_run"], "EXTRACTION_CONCURRENCY", 1
    )
    install_fake_embeddings(monkeypatch)


class _ScriptedModel:
    """Extracts one memory per transcript line starting "Remember:" and creates each one."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def respond(self, messages, info: AgentInfo) -> ModelResponse:
        prompt = "\n".join(
            part.content
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, UserPromptPart) and isinstance(part.content, str)
        )
        self.prompts.append(prompt)
        if prompt.startswith("Known memories"):
            args = {
                "memories": [
                    {
                        "title": fact.split(" is ")[0],
                        "content_md": fact,
                        "memory_type": "fact",
                        "evidence": fact,
                    }
                    for fact in re.findall(r"Remember: (.+)", prompt)
                ]
            }
        else:
            args = {
                "operations": [
                    {
                        "op": "create",
                        "title": title,
                        "content_md": content,
                        "memory_type": "fact",
                        "conversation": conversation,
                    }
                    for conversation, title, content in _CANDIDATE.findall(prompt)
                ]
            }
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, args, tool_call_id="out")]
        )

    @property
    def model(self) -> FunctionModel:
        return FunctionModel(self.respond, model_name="dream-test")


async def _finished_conversation(
    db: AsyncSession, context: MemoryContext, *, user, workspace, text: str, visibility: str
):
    conversation = build_conversation(user=user, workspace=workspace, visibility=visibility)
    db.add(conversation)
    await db.flush()
    run = AgentRun(
        conversation_id=conversation.id,
        agent_id=context.agent.id,
        workspace_id=workspace.id,
        user_id=user.id,
        trigger="interactive",
        status="completed",
        completed_at=datetime.now(UTC) - timedelta(hours=1),
    )
    db.add(run)
    await db.flush()
    await persist_new_messages(
        db,
        conversation=conversation,
        run_id=run.id,
        messages=[
            ModelRequest(parts=[UserPromptPart(text)]),
            ModelResponse(parts=[TextPart("Noted.")]),
        ],
    )
    return conversation


async def _workspace_run(db: AsyncSession, context: MemoryContext) -> MemoryDreamRun:
    """Reads the workspace's run under its tenant context, as the dream job does."""
    await set_session_tenant_context(db, workspace_id=context.workspace.id)
    return await db.scalar(
        select(MemoryDreamRun).where(MemoryDreamRun.workspace_id == context.workspace.id)
    )


async def _run_to_end(db: AsyncSession, run: MemoryDreamRun, model: FunctionModel) -> list[Job]:
    jobs: list[Job] = []
    while run.status not in {"completed", "failed"}:
        job = await db.scalar(
            select(Job).where(Job.content_hash == f"memory-dream:{run.id}:{run.status}")
        )
        jobs.append(job)
        await advance_dream_run(db, job, model=model)
    return jobs


async def test_dream_writes_each_conversation_to_the_scope_its_readers_share(
    db_session: AsyncSession, memory_context: MemoryContext
) -> None:
    colleague = build_user(email=f"colleague-{uuid4().hex}@example.com")
    db_session.add(colleague)
    await db_session.flush()
    db_session.add(
        build_workspace_membership(workspace_id=memory_context.workspace.id, user_id=colleague.id)
    )
    # Written first, so the test session's tenant ends on the dreaming workspace.
    elsewhere = build_workspace(slug=f"elsewhere-{uuid4().hex[:12]}")
    db_session.add(elsewhere)
    await db_session.flush()
    await _finished_conversation(
        db_session,
        memory_context,
        user=memory_context.user,
        workspace=elsewhere,
        visibility="workspace",
        text="Remember: Elsewhere code is 42.",
    )

    shared = await _finished_conversation(
        db_session,
        memory_context,
        user=memory_context.user,
        workspace=memory_context.workspace,
        visibility="workspace",
        text="Remember: Billing day is the 15th.",
    )
    private = await _finished_conversation(
        db_session,
        memory_context,
        user=colleague,
        workspace=memory_context.workspace,
        visibility="private",
        text="Remember: Reply length is short.",
    )
    await schedule_dreams(db_session, now=datetime.now(UTC))
    run = await _workspace_run(db_session, memory_context)
    scripted = _ScriptedModel()
    await _run_to_end(db_session, run, scripted.model)

    assert run.status == "completed"
    assert {entry["id"] for entry in run.conversations} == {str(shared.id), str(private.id)}
    assert all(UNTRUSTED_CONTENT_START in prompt for prompt in scripted.prompts)
    learned = {
        memory.title: memory
        for memory in await db_session.scalars(
            select(AgentMemory).where(AgentMemory.workspace_id == memory_context.workspace.id)
        )
    }
    assert set(learned) == {"Billing day", "Reply length"}
    billing, reply = learned["Billing day"], learned["Reply length"]
    assert (billing.scope, billing.user_id, billing.source_conversation_id) == (
        "workspace",
        None,
        shared.id,
    )
    assert (reply.scope, reply.user_id, reply.source_conversation_id) == (
        "user",
        colleague.id,
        private.id,
    )
    assert {billing.source, billing.created_by} == {"dream", "system"}


async def test_repeated_dream_step_changes_nothing(
    db_session: AsyncSession, memory_context: MemoryContext
) -> None:
    await _finished_conversation(
        db_session,
        memory_context,
        user=memory_context.user,
        workspace=memory_context.workspace,
        visibility="workspace",
        text="Remember: Billing day is the 15th.",
    )
    await schedule_dreams(db_session, now=datetime.now(UTC))
    run = await _workspace_run(db_session, memory_context)
    scripted = _ScriptedModel()
    jobs = await _run_to_end(db_session, run, scripted.model)
    calls = len(scripted.prompts)

    await advance_dream_run(db_session, jobs[-1], model=scripted.model)

    assert len(scripted.prompts) == calls
    learned = await db_session.scalar(
        select(func.count())
        .select_from(AgentMemory)
        .where(AgentMemory.workspace_id == memory_context.workspace.id)
    )
    assert learned == 1
    # A second schedule pass inside the interval starts no new dream.
    await schedule_dreams(db_session, now=datetime.now(UTC))
    runs = await db_session.scalar(
        select(func.count())
        .select_from(MemoryDreamRun)
        .where(MemoryDreamRun.workspace_id == memory_context.workspace.id)
    )
    assert runs == 1


async def test_capped_dream_leaves_the_rest_for_the_next_dream(
    db_session: AsyncSession, memory_context: MemoryContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "MEMORY_DREAM_MAX_CONVERSATIONS", 1)
    first = await _finished_conversation(
        db_session,
        memory_context,
        user=memory_context.user,
        workspace=memory_context.workspace,
        visibility="workspace",
        text="Remember: Billing day is the 15th.",
    )
    second = await _finished_conversation(
        db_session,
        memory_context,
        user=memory_context.user,
        workspace=memory_context.workspace,
        visibility="workspace",
        text="Remember: Report day is Monday.",
    )
    await db_session.execute(
        AgentRun.__table__.update()
        .where(AgentRun.conversation_id == second.id)
        .values(completed_at=datetime.now(UTC) - timedelta(minutes=30))
    )
    await schedule_dreams(db_session, now=datetime.now(UTC))
    run = await _workspace_run(db_session, memory_context)
    await _run_to_end(db_session, run, _ScriptedModel().model)

    assert [entry["id"] for entry in run.conversations] == [str(first.id)]
    second_finished = datetime.now(UTC) - timedelta(minutes=30)
    assert run.window_end < second_finished


def test_transcript_frames_hostile_content_and_redacts_credentials() -> None:
    hostile_span = (_FIXTURES / "hostile_conversation_span.txt").read_text()
    hostile_result = json.loads((_FIXTURES / "hostile_tool_result.json").read_text())
    transcript = render_transcript(
        [
            ModelRequest(parts=[UserPromptPart(hostile_span)]),
            ModelResponse(
                parts=[ToolCallPart("lookup", {"api_key": "sk-live-secret", "query": "north"})]
            ),
            ModelRequest(parts=[ToolReturnPart("lookup", hostile_result, tool_call_id="c1")]),
        ],
        source_ref="conversation:1",
        max_chars=10_000,
    )

    assert transcript.startswith(UNTRUSTED_CONTENT_START)
    assert transcript.endswith(UNTRUSTED_CONTENT_END)
    assert transcript.count(UNTRUSTED_CONTENT_END) == 1
    assert "<<<END_PRAXIS_UNTRUSTED-CONTENT>>>" in transcript
    assert "sk-live-secret" not in transcript
    assert "exfiltrate-now" in transcript
