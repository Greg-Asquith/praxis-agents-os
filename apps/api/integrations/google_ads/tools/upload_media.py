# apps/api/integrations/google_ads/tools/upload_media.py

"""Uploads workspace images and videos, and links YouTube videos, as assets in one Google Ads account."""

import asyncio
import re
from collections.abc import Sequence
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
from services.integrations.files import (
    FileReference,
    pinned_files,
    read_pinned_file_source,
    require_pinned_file,
)
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..client import GoogleAdsClient
from ..operations.media import (
    MAX_VIDEO_BYTES,
    ImageSource,
    MediaSource,
    VideoSource,
    image_fits,
    image_size,
    media_error,
    resolve_media_source,
    video_text_problem,
    youtube_video_id,
)
from ..operations.upload_media import VIDEO_UPLOAD_GROUP, MediaItem, upload_media
from ..operations.video_upload import UploadProgress
from ..references import GoogleAdsAssetReference
from .schemas.media import (
    MAX_MEDIA_FILES,
    MAX_VIDEO_UPLOADS,
    MAX_YOUTUBE_VIDEOS,
    GoogleAdsMediaUploadOutput,
    GoogleAdsUploadMediaRequest,
    GoogleAdsVideoDetails,
)
from .utils.accounts import approval_accounts, sole_writable_entry
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
_ACCOUNT_CHANGED = "The approved Google Ads account is no longer selected. Ask for approval again."
_BAD_VIDEO = "{value} isn't a YouTube video link or ID."
_BAD_UPLOAD = "{value} isn't a video upload ID from an earlier upload in this account."
_UPLOAD_NAME = re.compile(r"(?:customers/(\d+)/youTubeVideoUploads/)?(\d{1,32})")
_PROCESSING = (
    "Google is still processing this video, so it can't go in an asset group yet. Finish "
    "it later with its upload ID."
)
_STATE_UNKNOWN = (
    "Google Ads didn't say whether this video is ready. Finish it later with its upload ID."
)

type MediaFiles = Annotated[
    list[FileReference] | None,
    Field(
        max_length=MAX_MEDIA_FILES,
        description="Workspace JPEG, PNG, or GIF image Files, and MP4, MOV, or WebM video Files.",
    ),
]
type YouTubeVideos = Annotated[
    list[Annotated[str, Field(min_length=1, max_length=200)]] | None,
    Field(max_length=MAX_YOUTUBE_VIDEOS, description="YouTube video links or 11-character IDs."),
]
type VideoDetails = Annotated[
    list[GoogleAdsVideoDetails] | None,
    Field(
        max_length=MAX_MEDIA_FILES,
        description="Titles and descriptions for video Files; the title defaults to the name.",
    ),
]
type VideoUploads = Annotated[
    list[Annotated[str, Field(min_length=1, max_length=200)]] | None,
    Field(
        max_length=MAX_VIDEO_UPLOADS,
        description="Upload IDs of earlier video uploads that were still processing.",
    ),
]


async def google_ads_upload_media(
    ctx: RunContext[RuntimeDeps],
    files: MediaFiles = None,
    youtube_videos: YouTubeVideos = None,
    video_details: VideoDetails = None,
    video_uploads: VideoUploads = None,
) -> dict[str, Any]:
    selected = upload_entry(ctx.deps)
    video_ids, upload_ids = _checked_request(
        selected, files, youtube_videos, video_details, video_uploads
    )
    # Unattended runs have no approval to pin against; approved runs must match what was shown.
    reviewed = approved_display_args(ctx) if ctx.tool_call_approved else None

    async def operation(entry: ResolvedContextEntry) -> Any:
        client: GoogleAdsClient | None = None
        items: list[MediaItem] = []
        pending: PendingIntegrationOperationDetail | None = None

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, items, pending
            if reviewed is not None and reviewed.get("_accounts") != approval_accounts([entry]):
                raise ModelRetry(_ACCOUNT_CHANGED)
            pinned = pinned_files(reviewed) if reviewed is not None else None
            sources = await _sources(ctx.deps, files or ())
            _check_videos(sources, video_details)
            for source in sources:
                if (problem := source.problem) is not None:
                    code = (
                        "unsupported_video"
                        if isinstance(source, VideoSource)
                        else "unsupported_image"
                    )
                    raise media_error(problem, code)
                if pinned is not None:
                    require_pinned_file(
                        source.approval_details(),
                        pinned.get(str(source.file.id)),
                        provider_key="google_ads",
                        operation=_OPERATION,
                    )
            items = _items(sources, video_details, video_ids, upload_ids)
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
    entry = sole_writable_entry(deps.active_context)
    if entry is None:
        raise ModelRetry(
            "Media uploads go to one account. Ask the user to select exactly one writable "
            "Google Ads account in Active Context."
        )
    return entry


def _checked_request(
    entry: ResolvedContextEntry,
    files: Sequence[FileReference] | None,
    videos: Sequence[str] | None,
    details: Sequence[GoogleAdsVideoDetails] | None,
    uploads: Sequence[str] | None,
) -> tuple[list[str], list[str]]:
    """Refuses an empty or repeated request; returns the video IDs and upload IDs in order."""
    if not files and not videos and not uploads:
        raise ModelRetry("Choose at least one image or video File, or YouTube video.")
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
    file_ids = {reference.entity_id for reference in files or ()}
    for detail in details or ():
        if detail.file_id not in file_ids:
            raise ModelRetry("Give titles only for video Files in `files`.")
        for label, value in (("title", detail.title), ("description", detail.description)):
            if value is not None and (problem := video_text_problem(value, label=label)):
                raise ModelRetry(problem)
    if len({detail.file_id for detail in details or ()}) != len(details or ()):
        raise ModelRetry("Give each video File one title.")
    upload_ids = [_upload_id(entry, value) for value in uploads or ()]
    if len(set(upload_ids)) != len(upload_ids):
        raise ModelRetry("List each video upload once.")
    return ids, upload_ids


def _upload_id(entry: ResolvedContextEntry, value: str) -> str:
    """Reads an upload ID or resource name, refusing one from another account."""
    match = _UPLOAD_NAME.fullmatch(value.strip())
    if match is None or (match.group(1) and match.group(1) != entry.external_id):
        raise ModelRetry(_BAD_UPLOAD.format(value=value))
    return match.group(2)


def _check_videos(
    sources: Sequence[MediaSource], details: Sequence[GoogleAdsVideoDetails] | None
) -> None:
    videos = [source for source in sources if isinstance(source, VideoSource)]
    if any(detail.file_id not in {video.file.id for video in videos} for detail in details or ()):
        raise ModelRetry("Titles and descriptions go with video Files only.")
    # Videos upload one after another, and the tool's timeout allows for 1 GB.
    if sum(video.revision.size_bytes for video in videos) > MAX_VIDEO_BYTES:
        raise ModelRetry(
            "One call uploads at most 1 GB of video. Upload these video Files in separate calls."
        )


def _items(
    sources: Sequence[MediaSource],
    details: Sequence[GoogleAdsVideoDetails] | None,
    video_ids: Sequence[str],
    upload_ids: Sequence[str],
) -> list[MediaItem]:
    """Orders the work as the audit record lists it: images, videos, links, then finishes."""
    by_file = {detail.file_id: detail for detail in details or ()}
    videos = [source for source in sources if isinstance(source, VideoSource)]
    return [
        *(
            MediaItem("image", image=source)
            for source in sources
            if isinstance(source, ImageSource)
        ),
        *(
            MediaItem(
                "video",
                video=source,
                title=detail.title
                if (detail := by_file.get(source.file.id))
                else source.default_title,
                description=detail.description if detail else None,
                upload=UploadProgress(),
                intent_index=index,
            )
            for index, source in enumerate(videos)
        ),
        *(MediaItem("youtube_video", video_id=video_id) for video_id in video_ids),
        *(
            MediaItem("video", upload=UploadProgress(upload_id=upload_id))
            for upload_id in upload_ids
        ),
    ]


async def _sources(deps: RuntimeDeps, files: Sequence[FileReference]) -> list[MediaSource]:
    return [
        await resolve_media_source(deps.db, workspace_id=deps.workspace.id, file_id=ref.entity_id)
        for ref in files
    ]


async def _validate_args(
    ctx: RunContext[RuntimeDeps],
    files: MediaFiles = None,
    youtube_videos: YouTubeVideos = None,
    video_details: VideoDetails = None,
    video_uploads: VideoUploads = None,
) -> None:
    """Refuses unclear requests before approval; Files Google won't take show on the card."""
    entry = upload_entry(ctx.deps)
    _checked_request(entry, files, youtube_videos, video_details, video_uploads)
    try:
        sources = await _sources(ctx.deps, files or ())
    except IntegrationError as exc:
        raise ModelRetry(exc.user_message) from None
    _check_videos(sources, video_details)


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Pins each File's revision and the account, with each image's size and where it fits."""
    references = [FileReference.model_validate(value) for value in args.get("files") or ()]
    return {
        **args,
        "_accounts": approval_accounts([upload_entry(deps)]),
        "_files": [await _file_check(source) for source in await _sources(deps, references)],
    }


async def _file_check(source: MediaSource) -> dict[str, Any]:
    """What the card shows for one File; the image is read only when Google could take it."""
    if isinstance(source, VideoSource):
        return {
            **source.approval_details(),
            "kind": "video",
            "duration_ms": source.duration_ms,
            "default_title": source.default_title,
        }
    details = {**source.approval_details(), "kind": "image", "width": None, "height": None}
    if details["problem"] is not None:
        return {**details, "fits": [], "too_small": []}
    try:
        data = await read_pinned_file_source(
            source.revision, provider_key="google_ads", operation=_OPERATION
        )
    except IntegrationValidationError as exc:
        return {**details, "problem": exc.user_message, "fits": [], "too_small": []}
    size = image_size(data, source.revision.content_type)
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
    uploads = [item for item in items if item.video is not None]
    videos = [item for item in items if item.kind == "youtube_video"]
    finishes = [item for item in items if item.kind == "video" and item.video is None]
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
    if uploads:
        groups.append(
            IntegrationOperationIntentGroup(
                key=VIDEO_UPLOAD_GROUP,
                action="upload_media",
                entity_type="google_ads_youtube_video_upload",
                items=[_video_intent(item) for item in uploads],
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
    if finishes:
        groups.append(
            IntegrationOperationIntentGroup(
                key="video_upload:finish",
                action="create_video_asset",
                entity_type="google_ads_youtube_video_asset",
                items=[
                    IntegrationOperationIntent(
                        fields={"object": item.key, "upload_id": item.upload.upload_id or ""}
                    )
                    for item in finishes
                    if item.upload is not None
                ],
            )
        )
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry), intent_groups=groups
    )


def _video_intent(item: MediaItem) -> IntegrationOperationIntent:
    """A video File's provenance and its title; the title can't change after the upload."""
    if item.video is None:
        raise RuntimeError("A video upload needs its File")
    revision = item.video.revision
    return IntegrationOperationIntent(
        fields={
            "object": item.key,
            "file_id": str(item.video.file.id),
            "revision_id": str(revision.id),
            "content_hash": revision.content_hash,
            "content_type": revision.content_type,
            "size_bytes": revision.size_bytes,
            "title": item.title or "",
        }
    )


def _result(entry: ResolvedContextEntry, items: Sequence[MediaItem]) -> dict[str, Any]:
    return {
        "account_id": entry.external_id,
        "uploads": [_upload_row(entry, item) for item in items],
    }


def _upload_row(entry: ResolvedContextEntry, item: MediaItem) -> dict[str, Any]:
    image = item.image
    source = image or item.video
    name = image.file.name[:500] if image else (item.title or _video_name(item))
    error_code, message = _row_message(item)
    asset = None
    if item.asset_id is not None:
        asset = GoogleAdsAssetReference(
            customer_id=entry.external_id,
            asset_id=item.asset_id,
            asset_type="IMAGE" if image else "YOUTUBE_VIDEO",
            label=name,
            description=_description(item),
            scope_label=entry.display_name[:500],
        ).model_dump(mode="json")
    return {
        "kind": item.kind,
        "name": name,
        "outcome": item.result,
        "recovered": item.recovered,
        "asset": asset,
        "file_id": str(source.file.id) if source else None,
        "revision_id": str(source.revision.id) if source else None,
        "size_bytes": source.revision.size_bytes if source else None,
        "width": item.width,
        "height": item.height,
        "fits": item.fits,
        "video_id": item.video_id,
        "upload_id": item.upload.upload_id if item.upload else None,
        "duration_ms": item.video.duration_ms if item.video else None,
        "error_code": error_code,
        "message": message,
    }


def _video_name(item: MediaItem) -> str:
    if item.kind == "video" and item.upload is not None:
        return f"Video upload {item.upload.upload_id}"
    return f"YouTube video {item.video_id}"


def _row_message(item: MediaItem) -> tuple[str | None, str | None]:
    """The error code and message the row shows, or what a processing video waits for."""
    for outcome in (item.upload_outcome, item.outcome):
        if outcome is not None and outcome[0] != "applied":
            return outcome[2], outcome[3]
    if item.result == "processing":
        return None, _STATE_UNKNOWN if item.skip_reason == "state_unknown" else _PROCESSING
    return None, None


def _description(item: MediaItem) -> str:
    if item.kind != "image":
        return "YouTube video"
    if item.width and item.height:
        return f"Image, {item.width} x {item.height}"
    return "Image"


DEFINITION = RuntimeToolDefinition(
    name="google_ads_upload_media",
    function=google_ads_upload_media,
    description=(
        "Upload up to 20 workspace Files to the one writable Google Ads account selected in "
        "Active Context: images (JPEG, PNG, or GIF, at most 5,120 KB each) become image "
        "assets, and videos (MP4, MOV, or WebM, at most 1 GB in one call) go to an unlisted YouTube "
        "channel Google manages for the account, then become video assets once Google has "
        "processed them. Give each video a title in `video_details` (up to 100 characters, "
        "without < or >; it defaults to the File name and can't change later). A video still "
        "processing when the call ends returns its `upload_id`; pass it in `video_uploads` "
        "later to make its asset. Also links up to 20 YouTube videos by link or ID. The "
        "approval card shows each image's size and the shapes it fits: landscape 1.91:1 (at "
        "least 600 x 314), square 1:1 (300 x 300), portrait 4:5 (480 x 600), logo 1:1 "
        "(128 x 128), and landscape logo 4:1 (512 x 128). Each finished upload returns an "
        "asset reference. Uploading doesn't add the assets to campaigns or spend money."
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
    # A 1 GB video upload, then up to two minutes waiting for Google to process it.
    timeout=600,
    args_validator=_validate_args,
    output_model=GoogleAdsMediaUploadOutput,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    approval_display_args=_approval_display_args,
    approval_input_model=GoogleAdsUploadMediaRequest,
    # An edited File list is checked and pinned again before it can be approved.
    approval_review_fields=("files",),
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Uploading Media to Google Ads",
        completed_label="Uploaded Media to Google Ads",
        failed_label="Couldn't Upload Media to Google Ads",
        approval_title="Upload Media to Google Ads",
        approval_prompt="The agent wants to upload this media to Google Ads.",
        approve_label="Approve & Upload",
        # Every field is optional, so the card can add Files to a request that had only links.
        arg_fields=(
            ToolFieldPresentation(
                key="files",
                label="Files",
                format="entity_list",
                editable=True,
                secondary=True,
                entity_kind="file",
            ),
            ToolFieldPresentation(
                key="youtube_videos",
                label="YouTube Videos",
                format="list",
                editable=True,
                secondary=True,
            ),
            ToolFieldPresentation(
                key="video_details",
                label="Video Titles",
                format="structured",
                editable=True,
                secondary=True,
            ),
            ToolFieldPresentation(
                key="video_uploads",
                label="Earlier Video Uploads",
                format="list",
                editable=True,
                secondary=True,
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
