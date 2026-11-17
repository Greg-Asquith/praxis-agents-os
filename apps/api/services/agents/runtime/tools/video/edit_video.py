# apps/api/services/agents/runtime/tools/video/edit_video.py

"""Changes a workspace video by instruction with a catalogue video model and saves the result
as the File's next revision.

A clip generated or edited in Praxis chains from the provider's stored interaction, so
nothing is uploaded. Any other clip is uploaded, within the model's input length limit.
"""

import hashlib
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.exceptions import ToolFailed
from sqlalchemy import select

from core.exceptions.general import AppValidationError, ConflictError
from core.settings import settings
from models.files import File, FileRevision
from models.media_generation import MediaGeneration
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.entity_references.domain import FileReference
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_INTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_POLICY_APPROVAL,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.agents.runtime.tools.files.utils import revision_source_ref
from services.agents.runtime.tools.media_inputs import record_media_read_audit
from services.agents.runtime.tools.registry import runtime_tool
from services.agents.runtime.tools.video.generation import (
    HOW_TO_CHECK,
    MAX_PROMPT_CHARS,
    TOOL_TIMEOUT_SECONDS,
    clip_cost,
    own_record,
    resolve_media_model,
    start_generation,
    wait_for_clip,
)
from services.agents.runtime.tools.video.utils import probed_video, progress, workspace_video
from services.agents.runtime.untrusted import UntrustedContent, UntrustedNode
from services.documents.outputs import EditTarget, save_file_edit
from services.files.domain import GenerationProvenance
from services.files.utils import file_revision_ref, revision_video_metadata
from services.media.catalogue import (
    PROCESSED_IN,
    MediaModel,
    MediaModelRoute,
    available_media_models,
    available_route,
    default_media_model,
)
from services.media.generation import (
    ChainExpiredError,
    GeneratedVideo,
    VideoEditRequest,
    VideoGenerationError,
    video_backend,
)
from services.media.media_generations import settle_media_generation
from services.storage.factory import get_storage_provider

TASK = "edit_video"
TOOL_NAME = "edit_video"


def _model_labels() -> dict[str, str]:
    return {
        model.id: f"{model.label} · {PROCESSED_IN[model.processing]}"
        for model in available_media_models(TASK)
    }


_MODEL_LABELS = _model_labels()


async def _display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Shows the model that will run when the agent leaves it out, and what each model would
    cost for this clip once the probe has measured it."""
    default = default_media_model(TASK)
    display = {
        "model": default.id if default is not None else None,
        **{key: value for key, value in args.items() if value is not None},
    }
    clip = await _measured_clip(deps, args.get("base_revision_id"))
    if clip is None:
        return display
    seconds, resolution = clip
    # The provider bills the clip it reads as input and keeps its length in the output.
    display["_estimates"] = {
        model.id: f"{route.clip_estimate(resolution, seconds, input_seconds=seconds):.2f}"
        for model in available_media_models(TASK)
        if (route := available_route(model, TASK))
    }
    display["_estimate_basis"] = f"{seconds:.1f} s at {'4K' if resolution == '4k' else resolution}"
    return display


async def _measured_clip(deps: RuntimeDeps, base_revision_id: object) -> tuple[Decimal, str] | None:
    """Returns the base revision's length and output resolution, once the probe has run."""
    try:
        revision_id = UUID(str(base_revision_id))
    except ValueError:
        return None
    revision = await deps.db.scalar(
        select(FileRevision).where(
            FileRevision.id == revision_id, FileRevision.workspace_id == deps.workspace.id
        )
    )
    metadata = revision_video_metadata(revision)
    if metadata is None:
        return None
    short_side = min(metadata.width or 0, metadata.height or 0)
    resolution = "720p" if short_side <= 720 else "1080p" if short_side <= 1080 else "4k"
    return Decimal(metadata.duration_ms) / 1000, resolution


class EditVideoOutput(BaseModel):
    """Model-visible metadata for one edited workspace video."""

    name: str
    file_id: str
    revision_id: str
    revision_number: int
    base_revision_id: str
    reference: FileReference
    media_type: str
    size_bytes: int
    model: str
    cost_usd: str | None
    model_notes: UntrustedNode | None
    how_to_check: str


@runtime_tool(
    name=TOOL_NAME,
    provider="native",
    label="Edit Video",
    code_eligible=False,
    description=(
        'Change a workspace MP4 video by instruction, such as "make it dusk" or "remove the '
        "extra leg in the last shot\", and save the result as the File's next version. Pass the "
        "revision_id you last saw as base_revision_id; if the File changed since, nothing is "
        "saved. A clip made with generate_video or edit_video can be any length; any other clip "
        "must be 10 seconds or less, so cut a longer one with cut_video_clips first. Each call "
        "costs money, about the same as generating the clip. Name one change at a time and say "
        "what must stay the same. It takes one to several minutes. The UI plays the saved clip; "
        "don't link to it."
    ),
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_INTERNAL,
    supports_approval=True,
    supports_auto=True,
    default_policy=TOOL_POLICY_APPROVAL,
    takes_ctx=True,
    timeout=TOOL_TIMEOUT_SECONDS,
    output_model=EditVideoOutput,
    availability_check=lambda: bool(available_media_models(TASK)),
    approval_display_args=_display_args,
    presentation=ToolPresentation(
        icon="video",
        running_label="Editing a Video",
        completed_label="Edited {name}",
        failed_label="Couldn't Edit the Video",
        approval_title="Edit a Video",
        approval_prompt=(
            "The agent wants to change this video. The result is saved as a new version, and you "
            "can restore the previous one from Files."
        ),
        approve_label="Approve & Edit",
        arg_fields=(
            # The base revision belongs to this File, so approvals can't retarget the edit.
            ToolFieldPresentation(
                key="file_id", label="Video", format="entity", entity_kind="file"
            ),
            ToolFieldPresentation(
                key="instruction",
                label="Instruction",
                format="multiline",
                editable=True,
                placeholder="Describe the change to make",
            ),
            ToolFieldPresentation(
                key="model",
                label="Video Model",
                editable=True,
                options=tuple(_MODEL_LABELS),
                option_labels=_MODEL_LABELS,
            ),
        ),
    ),
)
async def edit_video(
    ctx: RunContext[RuntimeDeps],
    file_id: FileReference,
    instruction: Annotated[
        str,
        Field(description="The one change to make, and what must stay the same."),
    ],
    base_revision_id: Annotated[
        UUID, Field(description="The video's revision_id from the result you last saw.")
    ],
    model: Annotated[
        Annotated[str, Field(json_schema_extra={"enum": list(_MODEL_LABELS)})] | None,
        Field(description="Optional video model. Omit it unless the person named one."),
    ] = None,
) -> dict[str, object]:
    """Edits one clip, or returns the revision this call already paid for."""
    instruction = instruction.strip()
    if not instruction:
        raise ModelRetry("edit_video requires a non-empty instruction.")
    if len(instruction) > MAX_PROMPT_CHARS:
        raise ModelRetry(f"instruction must be at most {MAX_PROMPT_CHARS} characters.")
    entry, route = resolve_media_model(model, TASK)
    file, revision = await workspace_video(ctx, file_id, tool_name=TOOL_NAME)

    record = await own_record(ctx, TOOL_NAME)
    if record is not None and record.status == "saved":
        return await _saved_output(ctx, record, base_revision_id)
    if record is not None and record.status == "failed":
        raise ToolFailed(record.error or "The video couldn't be edited.")
    if record is None:
        if revision.id != base_revision_id:
            raise ModelRetry(_stale(revision.id))
        if file.content_type != "video/mp4":
            raise ModelRetry(
                "edit_video changes MP4 videos. Make an MP4 copy with cut_video_clips, then edit "
                "that."
            )
        record = await _start(ctx, entry, route, file, revision, instruction)

    await progress(ctx)("Editing Video")
    video = await wait_for_clip(ctx, record)
    return await _save(ctx, record, file, base_revision_id, instruction, video)


async def _start(
    ctx: RunContext[RuntimeDeps],
    entry: MediaModel,
    route: MediaModelRoute,
    file: File,
    revision: FileRevision,
    instruction: str,
) -> MediaGeneration:
    """Chains from the clip's stored interaction, or uploads the clip when there is none."""
    provider_model = route.provider_model(TASK)
    chain_id = _chain_id(revision, route)
    # An upload is checked before the paid record, so a long clip costs nothing.
    upload = None if chain_id else await _upload(ctx, file, revision, entry)

    async def send() -> str:
        backend = video_backend(route.route)
        if chain_id is not None:
            try:
                return await backend.start_edit(
                    VideoEditRequest(provider_model, instruction, previous_id=chain_id)
                )
            except ChainExpiredError:
                # Google no longer holds the clip, and nothing was billed, so upload it instead.
                try:
                    content = await _upload(ctx, file, revision, entry)
                except (ModelRetry, ToolFailed) as exc:
                    # Settles the record as failed rather than leaving it at requested.
                    raise VideoGenerationError(str(exc)) from exc
                return await backend.start_edit(
                    VideoEditRequest(provider_model, instruction, video=content)
                )
        return await backend.start_edit(VideoEditRequest(provider_model, instruction, video=upload))

    return await start_generation(ctx, task=TASK, entry=entry, route=route, send=send)


def _chain_id(revision: FileRevision, route: MediaModelRoute) -> str | None:
    """Returns the provider's ID for the call that made this exact revision, on this route."""
    if revision.generation is None:
        return None
    provenance = GenerationProvenance.model_validate(revision.generation)
    return provenance.external_id if provenance.route == route.route else None


async def _upload(
    ctx: RunContext[RuntimeDeps], file: File, revision: FileRevision, entry: MediaModel
) -> bytes:
    """Reads the clip to upload, refusing one longer than the model takes."""
    metadata = probed_video(revision)
    limit = entry.limits.max_input_seconds
    if limit is not None and metadata.duration_ms > limit * 1000:
        raise ModelRetry(
            f"{entry.label} edits uploaded clips of up to {limit} seconds, and this one is "
            f"{metadata.duration_ms / 1000:.1f}. Cut the shot to {limit} seconds or less with "
            "cut_video_clips, then edit the new clip."
        )
    if revision.size_bytes > settings.MAX_FILE_SIZE_VIDEO:
        raise ModelRetry(
            "This clip is too large to upload for editing. Cut a shorter or lower resolution "
            "clip with cut_video_clips, then edit that."
        )
    await record_media_read_audit(
        ctx,
        file.id,
        revision.id,
        operation="video_edit",
        tool_name=TOOL_NAME,
        details={"media_model": entry.id},
    )
    return await get_storage_provider().get_object(file_revision_ref(revision))


async def _save(
    ctx: RunContext[RuntimeDeps],
    record: MediaGeneration,
    file: File,
    base_revision_id: UUID,
    instruction: str,
    video: GeneratedVideo,
) -> dict[str, object]:
    deps = ctx.deps
    await progress(ctx)("Saving Video")
    target = EditTarget(
        file_id=file.id, revision_id=base_revision_id, name=file.name, media_type=video.media_type
    )
    try:
        async with deps.db.begin_nested():
            stored = await save_file_edit(
                deps,
                target=target,
                content=video.content,
                details={
                    "source": "video_edit",
                    "media_generation_id": str(record.id),
                    "base_revision_id": str(base_revision_id),
                },
            )
    except (AppValidationError, ConflictError) as exc:
        message = (
            "The video changed while it was being edited, so the edit wasn't saved."
            if isinstance(exc, ConflictError)
            else f"The clip was edited but couldn't be saved: {exc.message}"
        )
        await settle_media_generation(deps.db, record, "failed", error=message)
        raise ToolFailed(message) from exc
    revision = await deps.db.get(FileRevision, stored.revision_id)
    if revision is None:
        raise RuntimeError("The saved revision is missing")
    provenance = GenerationProvenance(
        route=record.route,
        media_model=record.media_model,
        provider_model=record.provider_model,
        external_id=record.external_id,
        task=TASK,
        prompt_digest=f"sha256:{hashlib.sha256(instruction.encode()).hexdigest()}",
        source_revision_id=base_revision_id,
    )
    revision.generation = provenance.model_dump(mode="json", exclude_none=True)
    await settle_media_generation(deps.db, record, "saved", revision=revision)
    edited = await deps.db.get(File, revision.file_id)
    if edited is None:
        raise RuntimeError("The edited File is missing")
    notes = video.thought_summary
    return {
        **_output(edited, revision, record, base_revision_id),
        "cost_usd": clip_cost(record, video),
        "model_notes": UntrustedContent(
            source_kind="video_generation_notes",
            source_ref=revision_source_ref(edited, revision),
            content=notes,
        )
        if notes
        else None,
    }


async def _saved_output(
    ctx: RunContext[RuntimeDeps], record: MediaGeneration, base_revision_id: UUID
) -> dict[str, object]:
    """Returns the revision this call already saved, without asking the provider again."""
    revision = await ctx.deps.db.get(FileRevision, record.revision_id)
    file = await ctx.deps.db.get(File, record.file_id) if record.file_id else None
    if revision is None or file is None or file.deleted:
        raise ToolFailed("This call's edit was saved, then deleted.")
    return {
        **_output(file, revision, record, base_revision_id),
        "cost_usd": None,
        "model_notes": None,
    }


def _output(
    file: File, revision: FileRevision, record: MediaGeneration, base_revision_id: UUID
) -> dict[str, object]:
    return {
        "name": file.name,
        "file_id": str(file.id),
        "revision_id": str(revision.id),
        "revision_number": revision.revision_number,
        "base_revision_id": str(base_revision_id),
        "reference": FileReference(
            entity_id=file.id,
            label=file.name,
            description=f"Edited video · version {revision.revision_number}",
        ),
        "media_type": revision.content_type,
        "size_bytes": revision.size_bytes,
        "model": record.media_model,
        "how_to_check": HOW_TO_CHECK,
    }


def _stale(current_revision_id: UUID) -> str:
    return (
        "The video changed after you last saw it, so nothing was sent or saved. Its current "
        f"revision is {current_revision_id}. Check it, then redo the edit with that "
        "base_revision_id."
    )
