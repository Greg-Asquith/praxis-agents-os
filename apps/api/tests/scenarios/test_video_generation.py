# apps/api/tests/scenarios/test_video_generation.py

"""generate_video: one paid call per tool call, saved as a labelled File, with any references
checked before Google is asked."""

import json

import pytest
from sqlalchemy import select

from core.database import set_session_tenant_context
from core.settings import settings
from models.ai_usage_event import AIUsageEvent
from models.files import File, FileRevision
from models.media_generation import MediaGeneration
from services.agents.runtime.entity_references.domain import FileReference
from tests.support.media import persist_analysed_video, persist_image
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
def backend(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    reset_storage_provider_cache()
    yield use_fake_video_backend(monkeypatch)
    reset_storage_provider_cache()


def _turn(call_id: str = "generate", **arguments) -> ToolTurn:
    return ToolTurn((ToolCall("generate_video", {"prompt": PROMPT, **arguments}, call_id),))


def _refs(*files: File) -> list[dict]:
    return [
        FileReference(entity_id=file.id, label=file.name).model_dump(mode="json") for file in files
    ]


async def _clip(db_session_factory, context, name: str, duration_ms: int = 3_000) -> File:
    return await persist_analysed_video(
        db_session_factory,
        workspace_id=context.workspace_id,
        user_id=context.user_id,
        name=name,
        duration_ms=duration_ms,
        speech=None,
    )


async def _image(db_session_factory, context, name: str) -> File:
    return await persist_image(
        db_session_factory, workspace_id=context.workspace_id, user_id=context.user_id, name=name
    )


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


async def test_references_are_sent_images_first_and_kept_in_the_provenance(
    db_session_factory, backend: FakeVideoBackend
) -> None:
    context = await _context(db_session_factory)
    cup = await _image(db_session_factory, context, "cup.png")
    table = await _image(db_session_factory, context, "table.png")
    pour = await _clip(db_session_factory, context, "pour.mp4")

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                _turn(image_file_ids=_refs(cup, table), reference_video_file_ids=_refs(pour)),
                "Done.",
            ]
        ),
    )

    assert result.run.status == "completed"
    [request] = backend.starts
    assert [(item.kind, item.content) for item in request.references] == [
        ("image", b"cup.png"),
        ("image", b"table.png"),
        ("video", b"pour.mp4"),
    ]
    async with db_session_factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context.workspace_id, user_id=context.user_id
        )
        [record] = (await db.scalars(select(MediaGeneration))).all()
        revision = await db.get_one(FileRevision, record.revision_id)
        assert revision.generation["task"] == "reference_to_video"
        assert revision.generation["reference_revision_ids"] == [
            str(cup.current_revision_id),
            str(table.current_revision_id),
            str(pour.current_revision_id),
        ]


async def test_reference_clips_are_limited_by_the_length_of_the_clip_to_make(
    db_session_factory, backend: FakeVideoBackend
) -> None:
    context = await _context(db_session_factory)
    clips = [await _clip(db_session_factory, context, f"shot-{n}.mp4") for n in range(3)]
    long_shot = await _clip(db_session_factory, context, "long.mp4", duration_ms=3_040)

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                # Omni takes one reference clip for a clip over 10 seconds.
                _turn("too-many", duration_seconds=12, reference_video_file_ids=_refs(*clips[:2])),
                _turn("too-long", reference_video_file_ids=_refs(long_shot)),
                _turn("three", duration_seconds=8, reference_video_file_ids=_refs(*clips)),
                "Done.",
            ]
        ),
    )

    assert result.run.status == "completed"
    messages = str([message.parts for message in result.messages])
    assert "takes 1 reference clip for a 12 second clip" in messages
    assert "cut_video_clips" in messages
    [request] = backend.starts
    assert [item.content for item in request.references] == [
        b"shot-0.mp4",
        b"shot-1.mp4",
        b"shot-2.mp4",
    ]


async def test_a_reference_of_the_wrong_type_or_from_another_workspace_sends_nothing(
    db_session_factory, backend: FakeVideoBackend
) -> None:
    other = await build_scenario_agent(db_session_factory)
    foreign = await _image(db_session_factory, other, "their-logo.png")
    context = await _context(db_session_factory)
    clip = await _clip(db_session_factory, context, "shot.mp4")

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                _turn("foreign", image_file_ids=_refs(foreign)),
                _turn("clip-as-image", image_file_ids=_refs(clip)),
                "Done.",
            ]
        ),
    )

    assert result.run.status == "completed"
    assert backend.starts == []
    messages = str([message.parts for message in result.messages])
    assert "File not found" in messages
    assert "must be PNG, JPEG, or WebP" in messages
    async with db_session_factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context.workspace_id, user_id=context.user_id
        )
        assert (await db.scalars(select(MediaGeneration))).all() == []
