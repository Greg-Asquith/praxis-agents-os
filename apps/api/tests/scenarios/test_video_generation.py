# apps/api/tests/scenarios/test_video_generation.py

"""generate_video: one paid call per tool call, saved as a labelled File."""

import json

import pytest
from sqlalchemy import select

from core.database import set_session_tenant_context
from models.ai_usage_event import AIUsageEvent
from models.files import File, FileRevision
from models.media_generation import MediaGeneration
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)
from tests.support.storage import reset_storage_provider_cache
from tests.support.video_generation import FakeVideoBackend, use_fake_video_backend

PROMPT = "A ceramic coffee cup on a wooden table, steam rising. Slow push-in."


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch):
    yield use_fake_video_backend(monkeypatch)
    reset_storage_provider_cache()


def _turn(call_id: str = "generate", **arguments) -> ToolTurn:
    return ToolTurn((ToolCall("generate_video", {"prompt": PROMPT, **arguments}, call_id),))


async def _context(db_session_factory):
    return await build_scenario_agent(
        db_session_factory,
        tool_names=["generate_video"],
        tool_policies={"generate_video": "auto"},
    )


async def test_a_generated_clip_is_saved_once_with_provenance_and_metered(
    db_session_factory, backend: FakeVideoBackend
) -> None:
    context = await _context(db_session_factory)

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(turns=[_turn(duration_seconds=4), _turn(), "Done."]),
    )

    assert result.run.status == "completed"
    # The second call has the same tool call ID, so it returns the saved File unpaid.
    [request] = backend.starts
    assert (request.provider_model, request.aspect_ratio, request.duration_seconds) == (
        "gemini-omni-1.2-flash",
        "9:16",
        4,
    )
    assert backend.waits == ["interaction-1"]
    first, second = result.tool_returns("generate_video")
    assert first["content"]["file_id"] == second["content"]["file_id"]
    # The provider's notes are model text, so they reach the agent framed as untrusted.
    assert first["content"]["model_notes"]["node"] == "praxis_untrusted"
    async with db_session_factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context.workspace_id, user_id=context.user_id
        )
        [file] = (await db.scalars(select(File).where(File.category == "video"))).all()
        revision = await db.get_one(FileRevision, file.current_revision_id)
        assert revision.generation["external_id"] == "interaction-1"
        assert revision.generation["prompt_digest"].startswith("sha256:")
        [record] = (await db.scalars(select(MediaGeneration))).all()
        assert (record.status, record.revision_id) == ("saved", revision.id)
        [usage] = (
            await db.scalars(select(AIUsageEvent).where(AIUsageEvent.purpose == "video_generation"))
        ).all()
        assert (usage.model, usage.output_tokens, usage.requests) == (
            "gemini-omni-1.2-flash",
            24_293,
            1,
        )


async def test_a_call_whose_clip_is_running_waits_on_it_without_paying_again(
    db_session_factory, backend: FakeVideoBackend
) -> None:
    context = await _context(db_session_factory)
    async with db_session_factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context.workspace_id, user_id=context.user_id
        )
        db.add(
            MediaGeneration(
                workspace_id=context.workspace_id,
                run_id=context.run_id,
                tool_call_id="generate",
                task="text_to_video",
                media_model="omni-1.2-flash",
                route="google",
                provider_model="gemini-omni-1.2-flash",
                external_id="interaction-earlier",
                status="running",
            )
        )
        await db.commit()

    result = await run_scenario(
        db_session_factory, context, model=scripted_model(turns=[_turn(), "Done."])
    )

    assert result.run.status == "completed"
    assert backend.starts == []
    assert backend.waits == ["interaction-earlier"]


async def test_a_refused_prompt_saves_nothing_and_asks_for_a_revision(
    db_session_factory, backend: FakeVideoBackend
) -> None:
    backend.refuse = True
    context = await _context(db_session_factory)

    result = await run_scenario(
        db_session_factory, context, model=scripted_model(turns=[_turn(), "Done."])
    )

    assert result.run.status == "completed"
    assert result.tool_returns("generate_video") == []
    assert "declined" in json.dumps([message.parts for message in result.messages])
    async with db_session_factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context.workspace_id, user_id=context.user_id
        )
        assert (await db.scalars(select(File).where(File.category == "video"))).all() == []
        [record] = (await db.scalars(select(MediaGeneration))).all()
        assert record.status == "failed"
        # Google may bill a clip it refused late, so the call is metered without tokens.
        [usage] = (
            await db.scalars(select(AIUsageEvent).where(AIUsageEvent.purpose == "video_generation"))
        ).all()
        assert usage.details["unmeasured_requests"] == 1
