# apps/api/integrations/meta_ads/tools/upload_media.py

"""Uploads workspace images and videos to one ad account's media library after approval."""

import asyncio
from collections.abc import Mapping, Sequence
from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from core.exceptions.integration import IntegrationError
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

from ..client import MetaAdsClient
from ..operations.media_source import MediaSource, require_pinned, resolve_media_source
from ..operations.upload_media import MediaUpload, media_upload_row, upload_media
from ..settings import meta_ads_settings
from ..throttle import ensure_account_available
from .schemas.media import MetaAdsMediaUploadOutput
from .utils.bindings import META_ADS_WRITE_BINDING, RESULTS_FIELD
from .utils.client import meta_ads_available, meta_ads_client
from .utils.mutation_evidence import (
    account_pin,
    attach_interrupted_evidence,
    audit_status,
    meta_ads_account_target,
    terminal_operation_detail,
)

_OPERATION = "upload_media"
_MAX_FILES = 20
_ACCOUNT_CHANGED = "The approved ad account is no longer selected. Ask for approval again."

type MediaFiles = Annotated[
    list[FileReference],
    Field(min_length=1, max_length=_MAX_FILES, description="Workspace image or video Files."),
]


async def meta_ads_upload_media(ctx: RunContext[RuntimeDeps], files: MediaFiles) -> dict[str, Any]:
    _require_distinct(files)
    selected = upload_entry(ctx.deps)
    # Auto runs have no approval to pin against; approved runs must match what was shown.
    reviewed = approved_display_args(ctx) if ctx.tool_call_approved else None

    async def operation(entry: ResolvedContextEntry) -> Any:
        client: MetaAdsClient | None = None
        sources: list[MediaSource] = []
        pending_detail: PendingIntegrationOperationDetail | None = None

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, sources, pending_detail
            if reviewed is not None and reviewed.get("_account") != account_pin(entry):
                raise ModelRetry(_ACCOUNT_CHANGED)
            ensure_account_available(entry.external_id, operation=_OPERATION)
            sources = await _sources(ctx.deps, files)
            if reviewed is not None:
                pinned = _pinned_files(reviewed)
                for source in sources:
                    require_pinned(source, pinned.get(str(source.file.id)))
            client = await meta_ads_client(ctx, entry)
            pending_detail = _pending_operation_detail(entry, sources)
            return pending_detail

        async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
            if client is None or pending_detail is None or not sources:
                raise RuntimeError("Meta Ads media upload preparation did not complete")
            try:
                uploads, ledger = await upload_media(
                    client,
                    account_id=entry.external_id,
                    scope_label=entry.display_name,
                    sources=sources,
                    poll_seconds=meta_ads_settings.META_ADS_VIDEO_PROCESSING_POLL_SECONDS,
                )
            except (asyncio.CancelledError, Exception) as exc:
                attach_interrupted_evidence(exc, pending_detail, identity_key="file_id")
                raise
            detail = terminal_operation_detail(pending_detail, ledger, identity_key="file_id")
            result = _result(entry.external_id, uploads)
            outcome_status = audit_status(detail)
            return IntegrationAuditOutcome(
                result,
                status=outcome_status,
                external_ref=",".join(ledger.external_refs)[:1000] or None,
                operation_detail=detail,
                unverified_result=result if outcome_status is AuditStatus.UNVERIFIED else None,
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="meta_ads_upload_media",
            operation=_OPERATION,
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )

    results = await run_context_scope(
        ctx,
        binding=META_ADS_WRITE_BINDING,
        provider_scope_id=selected.external_id,
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


def upload_entry(deps: RuntimeDeps) -> ResolvedContextEntry:
    """Picks the one writable ad account in Active Context; the agent never names accounts."""
    active = deps.active_context
    entries = active.compatible_entries(META_ADS_WRITE_BINDING) if active else ()
    writable = [entry for entry in entries if entry.write_allowed]
    candidates = writable or (list(entries) if len(entries) == 1 else [])
    if len(candidates) != 1:
        raise ModelRetry(
            "Media uploads go to one ad account. Ask the user to select exactly one writable "
            "Meta ad account in Active Context."
        )
    return candidates[0]


def _require_distinct(files: Sequence[FileReference]) -> None:
    if len({reference.entity_id for reference in files}) != len(files):
        raise ModelRetry("Choose each File once.")


async def _sources(deps: RuntimeDeps, files: Sequence[FileReference]) -> list[MediaSource]:
    return [
        await resolve_media_source(deps.db, workspace=deps.workspace, reference=reference)
        for reference in files
    ]


async def _validate_args(ctx: RunContext[RuntimeDeps], files: MediaFiles) -> None:
    """Rejects Files Meta won't take, and an unclear account, before approval is requested."""
    _require_distinct(files)
    upload_entry(ctx.deps)
    try:
        await _sources(ctx.deps, files)
    except IntegrationError as exc:
        raise ModelRetry(exc.user_message) from None


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Pins each File's revision and the destination account to what the approver sees."""
    entry = upload_entry(deps)
    references = [FileReference.model_validate(value) for value in args.get("files") or ()]
    sources = await _sources(deps, references)
    return {
        **args,
        "_account": account_pin(entry),
        "_account_name": entry.display_name[:500],
        "_files": [source.approval_details() for source in sources],
    }


def _pinned_files(reviewed: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    files = reviewed.get("_files")
    if not isinstance(files, list):
        return {}
    return {str(item.get("file_id")): item for item in files if isinstance(item, Mapping)}


def _pending_operation_detail(
    entry: ResolvedContextEntry, sources: Sequence[MediaSource]
) -> PendingIntegrationOperationDetail:
    return PendingIntegrationOperationDetail(
        target=meta_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key="media:upload",
                action="upload_media",
                entity_type="meta_ads_media",
                items=[
                    IntegrationOperationIntent(
                        fields={
                            "file_id": str(source.file.id),
                            "revision_id": str(source.revision.id),
                            "content_hash": source.revision.content_hash,
                            "content_type": source.revision.content_type,
                            "size_bytes": source.revision.size_bytes,
                            "media_type": source.media_type,
                        }
                    )
                    for source in sources
                ],
            )
        ],
    )


def _result(account_id: str, uploads: Sequence[MediaUpload]) -> dict[str, Any]:
    return {"account_id": account_id, "uploads": [media_upload_row(upload) for upload in uploads]}


DEFINITION = RuntimeToolDefinition(
    name="meta_ads_upload_media",
    function=meta_ads_upload_media,
    description=(
        "Upload up to 20 workspace Files, JPEG or PNG images and MP4 or MOV videos, to the "
        "media library of the one writable Meta ad account selected in Active Context. Each "
        "upload returns a media reference to pass to ad creation as is. Upload videos before "
        "creating ads with them: Meta processes a video for a few minutes, and a video "
        "not returned as ready can be used only once meta_ads_list_assets shows it ready. "
        "Uploading doesn't create ads or spend money."
    ),
    provider="meta_ads",
    label="Upload Media to Meta Ads",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    # Sends workspace content to Meta without setting up spend, so admins may trust it.
    supports_auto=True,
    takes_ctx=True,
    timeout=300,
    args_validator=_validate_args,
    output_model=MetaAdsMediaUploadOutput,
    integration_binding=META_ADS_WRITE_BINDING,
    availability_check=meta_ads_available,
    approval_display_args=_approval_display_args,
    # An edited File list is checked and pinned again before it can be approved.
    approval_review_fields=("files",),
    presentation=ToolPresentation(
        icon="meta_ads",
        running_label="Uploading Media to Meta Ads",
        completed_label="Uploaded Media to Meta Ads",
        failed_label="Couldn't Upload Media to Meta Ads",
        approval_title="Upload Media to Meta Ads",
        approval_prompt="The agent wants to upload these Files to the Meta ad account {_account_name}.",
        approve_label="Approve & Upload",
        arg_fields=(
            ToolFieldPresentation(
                key="files", label="Files", format="entity_list", editable=True, entity_kind="file"
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
