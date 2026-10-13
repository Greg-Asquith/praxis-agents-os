# apps/api/tests/services/jobs/test_probe_video.py

"""Video probe job: what a File keeps from the renderer's measurement."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from services.jobs.handlers.probe_video import probe_video
from services.media.domain import MediaRendererError
from tests.factories import build_file, build_file_revision, build_job, build_workspace
from tests.support.media import use_fake_renderer
from tests.support.storage import reset_storage_provider_cache

pytestmark = pytest.mark.asyncio

PROBE = {
    "duration_ms": 3_612_480,
    "width": 1920,
    "height": 1080,
    "fps": 29.97,
    "video_codec": "h264",
    "has_audio": True,
    "audio_codec": "aac",
    "rotation": 0,
}


@pytest.fixture
def renderer_answers(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[list[object]]:
    """Local storage plus a renderer that answers each probe with the next queued result."""
    answers: list[object] = []

    async def fake_post(payload: dict) -> dict:
        assert payload["operation"] == "probe"
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return {"ok": True, "result": answer, "outputs": [], "elapsed_ms": 5}

    use_fake_renderer(monkeypatch, tmp_path, fake_post)
    try:
        yield answers
    finally:
        reset_storage_provider_cache()


async def _pending_video(db: AsyncSession):
    workspace = build_workspace(slug=f"probe-{uuid4().hex[:8]}")
    file = build_file(
        workspace=workspace,
        name="source.mp4",
        category="video",
        content_type="video/mp4",
        extension=".mp4",
        processing_status="pending",
    )
    db.add(workspace)
    await db.flush()
    db.add(file)
    await db.flush()
    revision = build_file_revision(file, created_by_system=True)
    db.add(revision)
    await db.flush()
    file.current_revision_id = revision.id
    file.revision_count = 1
    await db.flush()
    job = build_job(
        kind="video.probe",
        workspace_id=workspace.id,
        subject_type="file_revision",
        subject_id=revision.id,
        payload={"file_id": str(file.id), "revision_id": str(revision.id)},
        content_hash=revision.content_hash,
    )
    return file, revision, job


async def _run(db: AsyncSession, job) -> None:
    await probe_video(db, job)
    await db.flush()


async def test_probe_stores_the_measurement_and_marks_the_file_ready(
    db_session: AsyncSession, renderer_answers: list[object]
) -> None:
    file, revision, job = await _pending_video(db_session)
    renderer_answers.append(PROBE)

    await _run(db_session, job)
    await db_session.refresh(file)
    await db_session.refresh(revision)

    assert revision.media_metadata == PROBE
    assert file.processing_status == "ready"
    assert file.processing_error is None


async def test_audio_only_file_fails_processing_without_a_retry(
    db_session: AsyncSession, renderer_answers: list[object]
) -> None:
    file, revision, job = await _pending_video(db_session)
    renderer_answers.append(
        {**PROBE, "width": None, "height": None, "fps": None, "video_codec": None}
    )

    await _run(db_session, job)
    await db_session.refresh(file)
    await db_session.refresh(revision)

    assert file.processing_status == "error"
    assert revision.media_metadata is None


async def test_video_over_the_duration_limit_fails_processing(
    db_session: AsyncSession,
    renderer_answers: list[object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "VIDEO_MAX_SOURCE_DURATION_SECONDS", 3600)
    file, revision, job = await _pending_video(db_session)
    renderer_answers.append(PROBE)

    await _run(db_session, job)
    await db_session.refresh(file)
    await db_session.refresh(revision)

    assert file.processing_status == "error"
    assert file.processing_error == "The video is 1:00:12 long. Videos can be up to 1:00:00."
    assert revision.media_metadata is None


async def test_renderer_outage_fails_the_attempt_so_the_job_retries(
    db_session: AsyncSession, renderer_answers: list[object]
) -> None:
    file, revision, job = await _pending_video(db_session)
    renderer_answers.append(MediaRendererError("unavailable", "The renderer couldn't be reached."))

    with pytest.raises(MediaRendererError):
        await _run(db_session, job)
    await db_session.refresh(file)

    assert file.processing_status == "error"
    assert file.processing_attempts == 1

    renderer_answers.append(PROBE)
    await _run(db_session, job)
    await db_session.refresh(file)
    await db_session.refresh(revision)

    assert file.processing_status == "ready"
    assert revision.media_metadata == PROBE
