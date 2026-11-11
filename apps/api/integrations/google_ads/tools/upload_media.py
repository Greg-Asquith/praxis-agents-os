# apps/api/integrations/google_ads/tools/upload_media.py

"""Uploads workspace images and links YouTube videos as assets in one Google Ads account."""

import asyncio
from collections.abc import Mapping, Sequence
from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from core.exceptions.integration import IntegrationError, IntegrationValidationError
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_EXTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_EXTERNAL_WRITE,
    TOOL_POLICY_APPROVAL,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.audit_events import (
    AuditStatus,
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    PendingIntegrationOperationDetail,
)
from services.integrations.approved_display_args import approved_display_args
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.context.targeted import run_context_scope
from services.integrations.files import FileReference
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..client import GoogleAdsClient
from ..operations.media import (
    ImageSource,
    image_fits,
    image_size,
    read_image,
    require_uploadable,
    resolve_image_source,
    youtube_video_id,
)
from ..operations.upload_media import MediaItem, upload_media
from ..references import GoogleAdsAssetReference
from .schemas.media import MAX_MEDIA_FILES, MAX_YOUTUBE_VIDEOS, GoogleAdsMediaUploadOutput
from .utils.bindings import GOOGLE_ADS_WRITE_BINDING, RESULTS_FIELD
from .utils.client import google_ads_available, google_ads_client
from .utils.mutation_evidence import (
    attach_interrupted_evidence,
    audit_status,
    google_ads_account_target,
    terminal_operation_detail,
)
from .utils.routing import login_customer_id

_OPERATION = "upload_media"
_IDENTITY = ("object",)
_ACCOUNT_CHANGED = (
    "The selected Google Ads account changed after approval. Ask the agent to prepare the "
    "upload again."
)
_BAD_VIDEO = "{value} isn't a YouTube video link or ID."

type ImageFiles = Annotated[
    list[FileReference] | None,
    Field(max_length=MAX_MEDIA_FILES, description="Workspace JPEG, PNG, or GIF image Files."),
]
type YouTubeVideos = Annotated[
    list[Annotated[str, Field(min_length=1, max_length=200)]] | None,
    Field(max_length=MAX_YOUTUBE_VIDEOS, description="YouTube video links or 11-character IDs."),
]


async def google_ads_upload_media(
    ctx: RunContext[RuntimeDeps],
    files: ImageFiles = None,
    youtube_videos: YouTubeVideos = None,
) -> dict[str, Any]:
    video_ids = _checked_request(files, youtube_videos)
    selected = upload_entry(ctx.deps)
    # Unattended runs have no approval to pin against; approved runs must match what was shown.
    reviewed = approved_display_args(ctx) if ctx.tool_call_approved else None

    async def operation(entry: ResolvedContextEntry) -> Any:
        client: GoogleAdsClient | None = None
        items: list[MediaItem] = []
        pending: PendingIntegrationOperationDetail | None = None

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, items, pending
            if reviewed is not None and reviewed.get("_account") != _account_pin(entry):
                raise ModelRetry(_ACCOUNT_CHANGED)
            pinned = _pinned_files(reviewed) if reviewed is not None else None
            sources = await _sources(ctx.deps, files or ())
            for source in sources:
                require_uploadable(
                    source, None if pinned is None else pinned.get(str(source.file.id), {})
                )
            items = [
                *(MediaItem("image", image=source) for source in sources),
                *(MediaItem("youtube_video", video_id=video_id) for video_id in video_ids),
            ]
            client = await google_ads_client(ctx, entry)
            pending = _pending_detail(entry, items)
            return pending

        async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
            if client is None or pending is None or not items:
                raise RuntimeError("Google Ads media upload preparation did not complete")
            try:
                ledger = await upload_media(
                    client,
                    customer_id=entry.external_id,
                    login_customer_id=login_customer_id(entry),
                    items=items,
                )
            except (asyncio.CancelledError, Exception) as exc:
                attach_interrupted_evidence(exc, pending, identity_keys=_IDENTITY)
                raise
            detail = terminal_operation_detail(pending, ledger, identity_keys=_IDENTITY)
            result = _result(entry, items)
            status = audit_status(detail)
            return IntegrationAuditOutcome(
                result,
                status=status,
                external_ref=",".join(ledger.external_refs)[:1000] or None,
                operation_detail=detail,
                unverified_result=result if status is AuditStatus.UNVERIFIED else None,
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_ads_upload_media",
            operation=_OPERATION,
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )

    results = await run_context_scope(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        provider_scope_id=selected.external_id,
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


def upload_entry(deps: RuntimeDeps) -> ResolvedContextEntry:
    """Picks the one writable account in Active Context; the agent never names accounts."""
    active = deps.active_context
    entries = active.compatible_entries(GOOGLE_ADS_WRITE_BINDING) if active else ()
    writable = [entry for entry in entries if entry.write_allowed]
    if len(writable) != 1:
        raise ModelRetry(
            "Media uploads go to one account. Ask the user to select exactly one writable "
            "Google Ads account in Active Context."
        )
    return writable[0]


def _checked_request(
    files: Sequence[FileReference] | None, videos: Sequence[str] | None
) -> list[str]:
    """Refuses an empty or repeated request; returns the video IDs in order."""
    if not files and not videos:
        raise ModelRetry("Choose at least one image File or YouTube video.")
    if len({reference.entity_id for reference in files or ()}) != len(files or ()):
        raise ModelRetry("Choose each File once.")
    ids = []
    for value in videos or ():
        video_id = youtube_video_id(value)
        if video_id is None:
            raise ModelRetry(_BAD_VIDEO.format(value=value))
        ids.append(video_id)
    if len(set(ids)) != len(ids):
        raise ModelRetry("List each YouTube video once.")
    return ids


def _account_pin(entry: ResolvedContextEntry) -> dict[str, str]:
    return {"customer_id": entry.external_id, "resource_id": str(entry.integration_resource_id)}


async def _sources(deps: RuntimeDeps, files: Sequence[FileReference]) -> list[ImageSource]:
    return [
        await resolve_image_source(deps.db, workspace_id=deps.workspace.id, file_id=ref.entity_id)
        for ref in files
    ]


def _pinned_files(reviewed: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    files = reviewed.get("_files")
    if not isinstance(files, list):
        return {}
    return {str(item.get("file_id")): item for item in files if isinstance(item, Mapping)}


async def _validate_args(
    ctx: RunContext[RuntimeDeps], files: ImageFiles = None, youtube_videos: YouTubeVideos = None
) -> None:
    """Refuses unclear requests before approval; Files Google won't take show on the card."""
    _checked_request(files, youtube_videos)
    upload_entry(ctx.deps)
    try:
        await _sources(ctx.deps, files or ())
    except IntegrationError as exc:
        raise ModelRetry(exc.user_message) from None


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Pins each File's revision and the account, with each image's size and where it fits."""
    entry = upload_entry(deps)
    references = [FileReference.model_validate(value) for value in args.get("files") or ()]
    return {
        **args,
        "_account": _account_pin(entry),
        "_account_name": entry.display_name[:500],
        "_files": [await _file_check(source) for source in await _sources(deps, references)],
    }


async def _file_check(source: ImageSource) -> dict[str, Any]:
    """What the card shows for one File; the image is read only when Google could take it."""
    details = {**source.approval_details(), "width": None, "height": None}
    if details["problem"] is not None:
        return {**details, "fits": [], "too_small": []}
    try:
        size = image_size(await read_image(source), source.revision.content_type)
    except IntegrationValidationError as exc:
        return {**details, "problem": exc.user_message, "fits": [], "too_small": []}
    if size is None:
        problem = f"{source.file.name} isn't a readable image."
        return {**details, "problem": problem, "fits": [], "too_small": []}
    fits, too_small = image_fits(*size)
    return {**details, "width": size[0], "height": size[1], "fits": fits, "too_small": too_small}


def _pending_detail(
    entry: ResolvedContextEntry, items: Sequence[MediaItem]
) -> PendingIntegrationOperationDetail:
    """Records each File's provenance, never its bytes, and each video ID."""
    images = [item.image for item in items if item.image is not None]
    videos = [item for item in items if item.kind == "youtube_video"]
    groups = []
    if images:
        groups.append(
            IntegrationOperationIntentGroup(
                key="image:upload",
                action="upload_media",
                entity_type="google_ads_image_asset",
                items=[
                    IntegrationOperationIntent(
                        fields={
                            "object": f"file:{source.file.id}",
                            "file_id": str(source.file.id),
                            "revision_id": str(source.revision.id),
                            "content_hash": source.revision.content_hash,
                            "content_type": source.revision.content_type,
                            "size_bytes": source.revision.size_bytes,
                        }
                    )
                    for source in images
                ],
            )
        )
    if videos:
        groups.append(
            IntegrationOperationIntentGroup(
                key="youtube_video:link",
                action="link_youtube_video",
                entity_type="google_ads_youtube_video_asset",
                items=[
                    IntegrationOperationIntent(
                        fields={"object": item.key, "video_id": item.video_id or ""}
                    )
                    for item in videos
                ],
            )
        )
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry), intent_groups=groups
    )


def _result(entry: ResolvedContextEntry, items: Sequence[MediaItem]) -> dict[str, Any]:
    return {
        "account_id": entry.external_id,
        "uploads": [_upload_row(entry, item) for item in items],
    }


def _upload_row(entry: ResolvedContextEntry, item: MediaItem) -> dict[str, Any]:
    image = item.image
    name = image.file.name[:500] if image else (item.title or f"YouTube video {item.video_id}")
    state, _ref, error_code, message = item.outcome or ("unverified", None, None, None)
    asset = None
    if item.asset_id is not None:
        asset = GoogleAdsAssetReference(
            customer_id=entry.external_id,
            asset_id=item.asset_id,
            asset_type="IMAGE" if image else "YOUTUBE_VIDEO",
            label=name,
            description=_description(item),
            scope_label=entry.display_name,
        ).model_dump(mode="json")
    return {
        "kind": item.kind,
        "name": name,
        "outcome": item.result,
        "recovered": item.recovered,
        "asset": asset,
        "file_id": str(image.file.id) if image else None,
        "revision_id": str(image.revision.id) if image else None,
        "size_bytes": image.revision.size_bytes if image else None,
        "width": item.width,
        "height": item.height,
        "fits": item.fits,
        "video_id": item.video_id,
        "error_code": error_code if state != "applied" else None,
        "message": message if state != "applied" else None,
    }


def _description(item: MediaItem) -> str:
    if item.kind == "youtube_video":
        return "YouTube video"
    if item.width and item.height:
        return f"Image, {item.width} x {item.height}"
    return "Image"


DEFINITION = RuntimeToolDefinition(
    name="google_ads_upload_media",
    function=google_ads_upload_media,
    description=(
        "Upload up to 20 workspace image Files (JPEG, PNG, or GIF, at most 5,120 KB each) as "
        "image assets, and link up to 20 YouTube videos by link or ID as video assets, in the "
        "one writable Google Ads account selected in Active Context. Videos stay on YouTube; "
        "this doesn't upload video Files. The approval card shows each image's size and the "
        "shapes it fits: landscape 1.91:1 (at least 600 x 314), square 1:1 (300 x 300), "
        "portrait 4:5 (480 x 600), logo 1:1 (128 x 128), and landscape logo 4:1 "
        "(512 x 128). Each upload returns an asset reference. Uploading doesn't add the "
        "assets to campaigns or spend money."
    ),
    provider="google_ads",
    label="Upload Media to Google Ads",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    # Sends workspace content to Google without setting up spend, so admins may trust it.
    supports_auto=True,
    takes_ctx=True,
    timeout=300,
    args_validator=_validate_args,
    output_model=GoogleAdsMediaUploadOutput,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    approval_display_args=_approval_display_args,
    # An edited File list is checked and pinned again before it can be approved.
    approval_review_fields=("files",),
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Uploading Media to Google Ads",
        completed_label="Uploaded Media to Google Ads",
        failed_label="Couldn't Upload Media to Google Ads",
        approval_title="Upload Media to Google Ads",
        approval_prompt="The agent wants to upload these images to the Google Ads account {_account_name}.",
        approve_label="Approve & Upload",
        arg_fields=(
            ToolFieldPresentation(
                key="files", label="Images", format="entity_list", editable=True, entity_kind="file"
            ),
            ToolFieldPresentation(
                key="youtube_videos", label="YouTube Videos", format="list", editable=True
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
