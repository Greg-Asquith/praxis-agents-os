# apps/api/tests/services/media/test_run_media_operation.py

"""Renderer client: what reaches the renderer, and what comes back into Files."""

from collections.abc import Iterator
from urllib.parse import unquote

import pytest
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select

from core.database import set_session_tenant_context
from models.files import File, FileUpload
from models.workspace import Workspace
from services.files.revision_actor import FileRevisionActor
from services.files.utils import sha256_hex
from services.media import run_media_operation, save_media_output
from services.media.domain import (
    CutOperation,
    CutSegment,
    FramesOperation,
    MediaOperation,
    MediaRendererError,
)
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider
from tests.factories.files import build_file, build_file_revision
from tests.factories.workspaces import build_workspace
from tests.support.media import (
    run_media_operation_module as run_module,
    staged_ref,
    use_fake_renderer,
)
from tests.support.scenario import build_scenario_agent
from tests.support.storage import reset_storage_provider_cache

PROBE = {
    "duration_ms": 4000,
    "width": 320,
    "height": 180,
    "fps": 30.0,
    "video_codec": "h264",
    "has_audio": True,
    "audio_codec": "aac",
    "rotation": 0,
}


@pytest.fixture
def renderer(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict]]:
    """Local storage plus a fake renderer that writes each requested output."""
    requests: list[dict] = []

    async def fake_post(payload: dict) -> dict:
        requests.append(payload)
        outputs = []
        for index, target in enumerate(payload["outputs"]):
            content = f"output-{index}".encode()
            await get_storage_provider().put_object(staged_ref(target["url"]), content)
            outputs.append({"size_bytes": len(content), "sha256": sha256_hex(content)})
        result = (
            PROBE
            if payload["operation"] == "probe"
            else {"times_ms": payload["arguments"]["times_ms"]}
        )
        return {"ok": True, "result": result, "outputs": outputs, "elapsed_ms": 5}

    use_fake_renderer(monkeypatch, tmp_path, fake_post)
    try:
        yield requests
    finally:
        reset_storage_provider_cache()


def _video(workspace):
    file = build_file(
        workspace=workspace,
        name="source.mp4",
        category="video",
        content_type="video/mp4",
        extension=".mp4",
        size_bytes=2_000_000_000,
    )
    return build_file_revision(file)


async def test_renderer_receives_only_server_built_urls_and_numeric_arguments(
    renderer: list[dict],
) -> None:
    workspace = build_workspace()
    revision = _video(workspace)

    result = await run_media_operation(
        workspace_id=workspace.id,
        sources=[revision],
        operation=FramesOperation(times_ms=(0, 500)),
    )

    [payload] = renderer
    assert payload["arguments"] == {"times_ms": [0, 500], "max_edge_px": 1280}
    [source] = payload["inputs"]
    assert source["size_bytes"] == 2_000_000_000
    assert source["url"].startswith("http://host.docker.internal:8000/")
    assert revision.object_key in unquote(source["url"])
    staging_prefix = f"platform/media-staging/{workspace.id}/"
    assert all(
        staged_ref(item["url"]).key.startswith(staging_prefix) for item in payload["outputs"]
    )
    assert [output.content_type for output in result.outputs] == ["image/jpeg", "image/jpeg"]


async def test_video_from_another_workspace_never_reaches_the_renderer(
    renderer: list[dict],
) -> None:
    workspace = build_workspace()
    segments = (
        CutSegment(input=0, start_ms=0, end_ms=1000),
        CutSegment(input=1, start_ms=0, end_ms=1000),
    )

    with pytest.raises(MediaRendererError) as error:
        await run_media_operation(
            workspace_id=workspace.id,
            sources=[_video(workspace), _video(build_workspace())],
            operation=CutOperation(segments=segments, width=1080, height=1920),
        )

    assert error.value.code == "forbidden"
    assert renderer == []


async def test_output_that_doesnt_match_the_report_is_refused_and_discarded(
    renderer: list[dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = build_workspace()
    real_post = run_module._post

    async def misreporting_post(payload: dict) -> dict:
        body = await real_post(payload)
        body["outputs"][0]["size_bytes"] += 1
        return body

    monkeypatch.setattr(run_module, "_post", misreporting_post)

    with pytest.raises(MediaRendererError) as error:
        await run_media_operation(
            workspace_id=workspace.id,
            sources=[_video(workspace)],
            operation=FramesOperation(times_ms=(0,)),
        )

    assert error.value.code == "invalid_response"
    staged = staged_ref(renderer[0]["outputs"][0]["url"])
    assert await get_storage_provider().stat_object(staged) is None


def test_operations_accept_only_numbers() -> None:
    adapter = TypeAdapter(MediaOperation)

    cut = {"name": "cut", "width": 1080, "height": 1920}
    for value in (
        {**cut, "segments": [{"input": 0, "start_ms": "/etc/passwd", "end_ms": 1000}]},
        {**cut, "segments": [{"input": 0, "start_ms": 0, "end_ms": 1000}], "filter": "x"},
    ):
        with pytest.raises(ValidationError):
            adapter.validate_python(value)


async def test_saved_output_keeps_cleanup_ownership_until_commit(
    committed_db_session_factory, renderer: list[dict]
) -> None:
    context = await build_scenario_agent(committed_db_session_factory)
    async with committed_db_session_factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context.workspace_id, user_id=context.user_id
        )
        workspace = await db.get(Workspace, context.workspace_id)
        operation = await run_media_operation(
            workspace_id=workspace.id,
            sources=[_video(workspace)],
            operation=FramesOperation(times_ms=(0,)),
        )
        [output] = operation.outputs

        # Another workspace, and the same key outside platform staging, are both refused.
        private_copy = output.model_copy(
            update={"ref": make_storage_object_ref(StorageBucket.PRIVATE, output.ref.key)}
        )
        for target, staged in ((build_workspace(), output), (workspace, private_copy)):
            with pytest.raises(MediaRendererError) as error:
                await save_media_output(
                    db,
                    workspace=target,
                    user_id=context.user_id,
                    output=staged,
                    name="still.jpg",
                    actor=FileRevisionActor(system=True),
                )
            assert error.value.code == "forbidden"
        await save_media_output(
            db,
            workspace=workspace,
            user_id=context.user_id,
            output=output,
            name="still.jpg",
            actor=FileRevisionActor(system=True),
        )
        await db.rollback()

    async with committed_db_session_factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context.workspace_id, user_id=context.user_id
        )
        [reservation] = await db.scalars(
            select(FileUpload).where(FileUpload.workspace_id == context.workspace_id)
        )
        assert reservation.consumed_at is None
        assert await db.get(File, reservation.file_id) is None
    provider = get_storage_provider()
    # The reservation owns the written bytes for the upload sweeper; staging stays as the retry source.
    destination = make_storage_object_ref(StorageBucket.PRIVATE, reservation.object_key)
    assert await provider.stat_object(destination) is not None
    assert await provider.stat_object(output.ref) is not None
