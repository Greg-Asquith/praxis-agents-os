# apps/api/tests/scenarios/test_video_editing.py

"""edit_video: one paid edit per tool call, saved as the File's next revision."""

from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import select

from core.database import set_session_tenant_context
from core.settings import settings
from models.files import File, FileRevision
from models.media_generation import MediaGeneration
from services.agents.runtime.tools.video import edit_video
from tests.support.media import file_tool_turn, persist_analysed_video
from tests.support.scenario import build_scenario_agent, run_scenario, scripted_model
from tests.support.storage import reset_storage_provider_cache
from tests.support.video_generation import CLIP, FakeVideoBackend, use_fake_video_backend

INSTRUCTION = "Make it dusk. Keep the cup and the camera move the same."
GENERATION = {
    "route": "google",
    "media_model": "omni-1.2-flash",
    "provider_model": "gemini-omni-1.2-flash",
    "external_id": "interaction-1",
    "task": "text_to_video",
    "prompt_digest": "sha256:" + "0" * 64,
}


@pytest.fixture
def backend(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    reset_storage_provider_cache()
    yield use_fake_video_backend(monkeypatch)
    reset_storage_provider_cache()


async def _context(db_session_factory):
    return await build_scenario_agent(
        db_session_factory, tool_names=["edit_video"], tool_policies={"edit_video": "auto"}
    )


async def _video(
    db_session_factory, context, *, duration_ms: int, generation: dict | None = None
) -> tuple[File, UUID]:
    file = await persist_analysed_video(
        db_session_factory,
        workspace_id=context.workspace_id,
        user_id=context.user_id,
        name="cup.mp4",
        duration_ms=duration_ms,
        speech=None,
    )
    async with db_session_factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context.workspace_id, user_id=context.user_id
        )
        revision = await db.get_one(FileRevision, file.current_revision_id)
        revision.generation = generation
        await db.commit()
        return file, revision.id


def _edit(file: File, base_revision_id: UUID, call_id: str = "edit"):
    return file_tool_turn(
        "edit_video",
        file,
        call_id,
        instruction=INSTRUCTION,
        base_revision_id=str(base_revision_id),
    )


async def _revisions(db_session_factory, context, file: File) -> list[FileRevision]:
    async with db_session_factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context.workspace_id, user_id=context.user_id
        )
        return list(
            (
                await db.scalars(
                    select(FileRevision)
                    .where(FileRevision.file_id == file.id)
                    .order_by(FileRevision.revision_number)
                )
            ).all()
        )


async def test_a_generated_clip_is_edited_by_chaining_once_and_saved_as_its_next_revision(
    db_session_factory, backend: FakeVideoBackend
) -> None:
    context = await _context(db_session_factory)
    # Longer than an upload may be: chaining sends no video, so the limit doesn't apply.
    file, base = await _video(
        db_session_factory, context, duration_ms=12_000, generation=GENERATION
    )

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(turns=[_edit(file, base), _edit(file, base), "Done."]),
    )

    assert result.run.status == "completed"
    [request] = backend.edits
    # The 1920x1080 source is kept at 1080p rather than Google's 720p default.
    assert (request.previous_id, request.video, request.resolution) == (
        "interaction-1",
        None,
        "1080p",
    )
    # The second call has the same tool call ID, so it returns the saved revision unpaid.
    first, second = result.tool_returns("edit_video")
    assert first["content"]["revision_id"] == second["content"]["revision_id"]
    original, edited = await _revisions(db_session_factory, context, file)
    assert str(edited.id) == first["content"]["revision_id"]
    assert edited.generation["external_id"] == "interaction-edit-1"
    assert edited.generation["source_revision_id"] == str(original.id)
    async with db_session_factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context.workspace_id, user_id=context.user_id
        )
        [record] = (await db.scalars(select(MediaGeneration))).all()
        assert (record.task, record.status, record.revision_id) == (
            "edit_video",
            "saved",
            edited.id,
        )


async def test_an_expired_chain_uploads_the_clip_instead(
    db_session_factory, backend: FakeVideoBackend
) -> None:
    backend.chain_expired = True
    context = await _context(db_session_factory)
    file, base = await _video(db_session_factory, context, duration_ms=9_500, generation=GENERATION)

    result = await run_scenario(
        db_session_factory, context, model=scripted_model(turns=[_edit(file, base), "Done."])
    )

    assert result.run.status == "completed"
    [request] = backend.edits
    assert (request.previous_id, request.video) == (None, b"cup.mp4")
    _, edited = await _revisions(db_session_factory, context, file)
    assert edited.size_bytes == len(CLIP)


async def test_an_uploaded_clip_over_ten_seconds_is_refused_before_any_paid_call(
    db_session_factory, backend: FakeVideoBackend
) -> None:
    context = await _context(db_session_factory)
    file, base = await _video(db_session_factory, context, duration_ms=10_030)

    result = await run_scenario(
        db_session_factory, context, model=scripted_model(turns=[_edit(file, base), "Done."])
    )

    assert result.run.status == "completed"
    assert backend.edits == []
    assert "cut_video_clips" in str([message.parts for message in result.messages])
    assert len(await _revisions(db_session_factory, context, file)) == 1
    async with db_session_factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context.workspace_id, user_id=context.user_id
        )
        assert (await db.scalars(select(MediaGeneration))).all() == []


async def test_a_stale_base_revision_sends_and_saves_nothing(
    db_session_factory, backend: FakeVideoBackend
) -> None:
    context = await _context(db_session_factory)
    file, _ = await _video(db_session_factory, context, duration_ms=5_000, generation=GENERATION)
    stale = UUID("00000000-0000-4000-8000-000000000001")

    result = await run_scenario(
        db_session_factory, context, model=scripted_model(turns=[_edit(file, stale), "Done."])
    )

    assert result.run.status == "completed"
    assert backend.edits == []
    assert "changed after you last saw it" in str([message.parts for message in result.messages])
    assert len(await _revisions(db_session_factory, context, file)) == 1


async def test_another_workspaces_video_is_refused_before_any_paid_call(
    db_session_factory, backend: FakeVideoBackend
) -> None:
    other = await build_scenario_agent(db_session_factory)
    foreign, base = await _video(
        db_session_factory, other, duration_ms=5_000, generation=GENERATION
    )
    context = await _context(db_session_factory)

    result = await run_scenario(
        db_session_factory, context, model=scripted_model(turns=[_edit(foreign, base), "Done."])
    )

    assert result.run.status == "completed"
    assert backend.edits == []
    assert "File not found" in str([message.parts for message in result.messages])


async def test_the_approval_estimates_the_edit_from_the_measured_clip(db_session_factory) -> None:
    context = await _context(db_session_factory)
    _file, base = await _video(db_session_factory, context, duration_ms=10_000)

    async with db_session_factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context.workspace_id, user_id=context.user_id
        )
        deps = SimpleNamespace(db=db, workspace=SimpleNamespace(id=context.workspace_id))
        display = await edit_video._display_args(
            deps, {"instruction": INSTRUCTION, "base_revision_id": str(base)}
        )

    # A 1920x1080 clip is priced at 1080p, and the clip read as input is billed too:
    # 10 s at $0.1043 output plus $0.0087 input a second.
    assert display["_estimates"] == {"omni-1.2-flash": "1.13"}
