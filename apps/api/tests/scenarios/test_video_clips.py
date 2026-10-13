# apps/api/tests/scenarios/test_video_clips.py

"""cut_video_clips against a fake renderer: per-clip results and saved Files."""

from collections.abc import Iterator
from urllib.parse import unquote, urlsplit

import pytest
from sqlalchemy import select

from models.files import File, FileRevision
from services.agents.runtime.entity_references.domain import FileReference
from services.files.utils import sha256_hex
from services.media.domain import MediaRendererError
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider
from tests.support.media import persist_analysed_video, staged_ref, use_fake_renderer
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)
from tests.support.storage import reset_storage_provider_cache

CLIP = {
    "duration_ms": 20_000,
    "width": 1080,
    "height": 1920,
    "fps": 30.0,
    "video_codec": "h264",
    "has_audio": True,
    "audio_codec": "aac",
    "rotation": 0,
}


@pytest.fixture
def renderer(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict]]:
    """A renderer that writes each clip, except one whose first segment starts at 30 s."""
    requests: list[dict] = []

    async def fake_post(payload: dict) -> dict:
        requests.append(payload)
        if payload["arguments"]["segments"][0][1] == 30_000:
            raise MediaRendererError("invalid_media", "The video couldn't be read.")
        content = b"clip-" + str(len(requests)).encode()
        [target] = payload["outputs"]
        await get_storage_provider().put_object(staged_ref(target["url"]), content)
        return {
            "ok": True,
            "result": CLIP,
            "outputs": [{"size_bytes": len(content), "sha256": sha256_hex(content)}],
            "elapsed_ms": 5,
        }

    use_fake_renderer(monkeypatch, tmp_path, fake_post)
    try:
        yield requests
    finally:
        reset_storage_provider_cache()


async def test_one_failed_clip_leaves_the_others_saved_and_reported(
    db_session_factory, renderer: list[dict]
) -> None:
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["cut_video_clips"],
        tool_policies={"cut_video_clips": "auto"},
    )
    talk = await persist_analysed_video(
        db_session_factory,
        workspace_id=context.workspace_id,
        user_id=context.user_id,
        name="Pricing talk.mp4",
        duration_ms=120_000,
        speech=(("Our pricing is per seat.", 10_000, 25_000),),
    )
    broll = await persist_analysed_video(
        db_session_factory,
        workspace_id=context.workspace_id,
        user_id=context.user_id,
        name="Office.mp4",
        duration_ms=8_000,
        speech=(),
    )

    def segment(file: File, start_ms: int | None = None, end_ms: int | None = None) -> dict:
        reference = FileReference(entity_id=file.id, label=file.name).model_dump(mode="json")
        return {"file_id": reference, "start_ms": start_ms, "end_ms": end_ms}

    clips = [
        {"segments": [segment(talk, 12_000, 20_000)]},
        {"segments": [segment(talk, 30_000, 40_000)]},
        {"segments": [segment(talk, 60_000, 70_000), segment(broll)], "name": "Ending"},
    ]
    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn(
                    (
                        ToolCall(
                            "cut_video_clips",
                            {"clips": clips, "aspect_ratio": "9:16", "captions": "bold"},
                            "cut_video_clips",
                        ),
                    )
                ),
                "Done.",
            ]
        ),
    )

    assert result.run.status == "completed"
    [output] = [part["content"] for part in result.tool_returns("cut_video_clips")]
    assert (output["saved"], output["failed"]) == (2, 1)
    assert [clip["status"] for clip in output["clips"]] == ["saved", "failed", "saved"]
    assert output["clips"][1]["error"] == "The video couldn't be read."
    # Clips render concurrently. The first snapped to its sentence; the last joined two videos.
    first, _, last = sorted(renderer, key=lambda request: request["arguments"]["segments"][0][1])
    assert first["arguments"]["segments"] == [[0, 10_000, 25_000]]
    assert last["arguments"]["segments"] == [[0, 60_000, 70_000], [1, 0, 8_000]]
    # Captions follow the videos as one more input, staged and removed after the render;
    # the last clip has no speech to caption.
    assert (len(first["inputs"]), first["arguments"]["captions"]) == (2, True)
    assert (len(last["inputs"]), last["arguments"]["captions"]) == (2, False)
    captions_key = unquote(urlsplit(first["inputs"][1]["url"]).path.split("/private/", 1)[1])
    assert captions_key.startswith(f"platform/media-staging/{context.workspace_id}/")
    assert (
        await get_storage_provider().stat_object(
            make_storage_object_ref(StorageBucket.PLATFORM_PRIVATE, captions_key)
        )
        is None
    )
    assert all(
        (request["arguments"]["width"], request["arguments"]["height"], request["arguments"]["fps"])
        == (1080, 1920, 30)
        for request in renderer
    )
    async with db_session_factory() as db:
        saved = (
            await db.execute(
                select(File, FileRevision)
                .join(FileRevision, FileRevision.id == File.current_revision_id)
                .where(
                    File.workspace_id == context.workspace_id,
                    File.id.not_in([talk.id, broll.id]),
                )
                .order_by(File.name)
            )
        ).all()
    assert [file.name for file, _ in saved] == ["Ending.mp4", "Pricing talk 0.10-0.25.mp4"]
    # The renderer measured each clip, so it is ready without a probe.
    assert all(
        file.processing_status == "ready" and revision.media_metadata == CLIP
        for file, revision in saved
    )
