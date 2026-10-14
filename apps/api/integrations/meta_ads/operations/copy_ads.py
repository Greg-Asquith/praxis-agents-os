# apps/api/integrations/meta_ads/operations/copy_ads.py

"""Copy existing ads into other ad sets: each copy sent once, renamed if asked, then read back."""

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from core.exceptions.integration import IntegrationError
from services.audit_events import IntegrationOperationCheckpoint
from services.integrations.operations import checkpoint_integration_operation

from ..client import MetaAdsClient
from ..creative_features import MetaAdsAdFormat, applied_changes, change_labels
from .ad_review import review_reasons, review_state
from .ad_rows import ad_effect, preview_url, unexpected_changes
from .create_ads import READ_FIELDS
from .create_objects import MetaCreateLookup, MetaCreateResult, create_object, read_created
from .mutations import (
    NOT_DISPATCHED_CODE,
    NOT_DISPATCHED_MESSAGE,
    MetaAdsMutationEffect,
    MetaAdsMutationLedger,
    MetaAdsMutationParent,
    freeze_fields,
    send_change,
)

OPERATION = "copy_ads"
COPY_GROUP = "ads:copy"
SOURCE_FIELDS = (
    "id,name,adset_id,campaign_id,status,effective_status,"
    "creative{id,body,image_hash,video_id,object_story_spec,asset_feed_spec,"
    "degrees_of_freedom_spec,contextual_multi_ads}"
)
_CONCURRENCY = 4
_EXCERPT = 125
_RENAME_FIELDS = {"change": "name"}
_NOT_RENAMED = (
    "Meta Ads copied this ad but didn't confirm its new name, so it may still be called {name}."
)
_READBACK_FAILED = "Meta Ads copied this ad, but it couldn't be read back."
_UNEXPECTED_CHANGES = (
    "Meta turned on automatic changes the source ad doesn't have: {labels}. "
    "Check it in Ads Manager."
)


@dataclass(frozen=True, slots=True)
class SourceAd:
    """What a copy carries from its source ad, read from Meta."""

    ad_id: str
    name: str
    adset_id: str | None
    format: MetaAdsAdFormat | None
    excerpt: str | None
    # Library media for the card's picture, as image:HASH or video:ID.
    media_key: str | None
    changes: frozenset[str]


def source_ad(row: Mapping[str, Any]) -> SourceAd:
    """Summarises a source ad's creative: format, text excerpt, picture, and changes on."""
    creative = row.get("creative")
    creative = creative if isinstance(creative, Mapping) else {}
    ad_format, text, media = _creative_parts(creative)
    return SourceAd(
        ad_id=str(row["id"]),
        name=str(row.get("name") or ""),
        adset_id=str(row["adset_id"]) if row.get("adset_id") else None,
        format=ad_format,
        excerpt=_excerpt(text),
        media_key=media,
        changes=applied_changes(creative),
    )


def _creative_parts(
    creative: Mapping[str, Any],
) -> tuple[MetaAdsAdFormat | None, Any, str | None]:
    story = _mapping(creative.get("object_story_spec"))
    link, video, photo = (
        _mapping(story.get(key)) for key in ("link_data", "video_data", "photo_data")
    )
    cards = link.get("child_attachments")
    if isinstance(cards, list) and cards:
        return "carousel", link.get("message"), _media(_mapping(cards[0]))
    if video:
        return "video", video.get("message"), _media(video)
    if link or photo:
        return "image", link.get("message") or photo.get("caption"), _media(link or photo)
    return None, creative.get("body"), _media(creative)


def _media(spec: Mapping[str, Any]) -> str | None:
    image_hash, video_id = spec.get("image_hash"), spec.get("video_id")
    if isinstance(video_id, str) and video_id.isascii() and video_id.isdigit():
        return f"video:{video_id}"
    if isinstance(image_hash, str) and image_hash.isascii() and image_hash.isalnum():
        return f"image:{image_hash}"
    return None


def _excerpt(text: Any) -> str | None:
    if not isinstance(text, str) or not text.strip():
        return None
    words = " ".join(text.split())
    return words if len(words) <= _EXCERPT else f"{words[:_EXCERPT].rstrip()}…"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


@dataclass(frozen=True, slots=True)
class PlannedCopy:
    """One source ad copied into one ad set, with its final name and status."""

    index: int
    key: str
    source: SourceAd
    adset_id: str
    adset_name: str | None
    name: str
    status: Literal["paused", "active"]
    # True when the source has an AI-generated change on, so the copy starts off.
    paused_for_ai: bool

    @property
    def renames(self) -> bool:
        return self.name != self.source.name


def intent_fields(plan: PlannedCopy) -> dict[str, str]:
    """Records the copy without any ad text: IDs, status, and the changes it carries."""
    return {
        "key": plan.key,
        "source_ad_id": plan.source.ad_id,
        "adset_id": plan.adset_id,
        "status": plan.status,
        "automatic_changes": ",".join(sorted(plan.source.changes)) or "none",
        "renamed": "true" if plan.renames else "false",
    }


@dataclass
class CopyRun:
    """What one planned copy proved."""

    plan: PlannedCopy
    fields: dict[str, str]
    outcome: MetaCreateResult | None = None
    # Set once the copy has been handed to Meta, so an interruption is unverified.
    sending: bool = False
    skip_code: str | None = None
    skip_message: str | None = None
    read: dict[str, Any] | None = None
    renaming: bool = False
    rename: MetaAdsMutationEffect | None = None

    @property
    def created_id(self) -> str | None:
        return self.outcome.object_id if self.outcome and self.outcome.status == "applied" else None

    @property
    def enabled(self) -> frozenset[str]:
        # A copy is expected to carry exactly what its source has on.
        return self.plan.source.changes


@dataclass
class CopyAdsRun:
    copies: list[CopyRun]

    def ledger(self) -> MetaAdsMutationLedger:
        return MetaAdsMutationLedger(
            action="copy_ads", parents=tuple(_parent(run) for run in self.copies)
        )


async def copy_ads(
    client: MetaAdsClient,
    *,
    account_id: str,
    planned: Sequence[PlannedCopy],
    intent_fields: Mapping[int, Mapping[str, str]],
) -> CopyAdsRun:
    """Copies every ad, renames copies that need a new name, then reads them back.

    Later copies continue after one fails. A copy's ID is checkpointed before its rename.

    Raises:
        asyncio.CancelledError: With a `ledger` attribute: copies being sent are unverified,
            and copies not reached are not dispatched.
    """
    run = CopyAdsRun([CopyRun(plan, dict(intent_fields[plan.index])) for plan in planned])
    try:
        semaphore = asyncio.Semaphore(_CONCURRENCY)

        async def send(copy_run: CopyRun) -> None:
            async with semaphore:
                await _copy_one(client, account_id, copy_run)

        async with asyncio.TaskGroup() as group:
            for copy_run in run.copies:
                group.create_task(send(copy_run))
        await _read_back(client, account_id, run)
    except (asyncio.CancelledError, Exception) as exc:
        exc.ledger = run.ledger()
        raise
    return run


async def _copy_one(client: MetaAdsClient, account_id: str, run: CopyRun) -> None:
    plan = run.plan
    # NO_RENAME keeps the source's name, so a lost reply is found by that name.
    lookup = MetaCreateLookup(
        name=plan.source.name,
        parent_field="adset.id",
        parent_id=plan.adset_id,
        since=datetime.now(UTC),
    )
    run.sending = True
    run.outcome = await create_object(
        client,
        account_id=account_id,
        edge="ads",
        path=f"{plan.source.ad_id}/copies",
        id_field="copied_ad_id",
        data={
            "adset_id": plan.adset_id,
            "status_option": "ACTIVE" if plan.status == "active" else "PAUSED",
            "rename_options": json.dumps({"rename_strategy": "NO_RENAME"}),
        },
        operation=OPERATION,
        lookup=lookup,
    )
    copied_id = run.created_id
    if copied_id is None or not plan.renames:
        return
    await checkpoint_integration_operation(
        IntegrationOperationCheckpoint(
            group_key=COPY_GROUP, intent_index=plan.index, references={"ad_id": copied_id}
        )
    )
    run.renaming = True
    failure = await send_change(
        client,
        account_id=account_id,
        object_id=copied_id,
        data={"name": plan.name},
        fields=_RENAME_FIELDS,
        operation=OPERATION,
    )
    run.rename = failure or MetaAdsMutationEffect(
        fields=freeze_fields(_RENAME_FIELDS), outcome="applied", external_ref=copied_id
    )


async def _read_back(client: MetaAdsClient, account_id: str, run: CopyAdsRun) -> None:
    """Reads every copy once; a failed read leaves the copies made but unverified."""
    copied = {copy_run.created_id: copy_run for copy_run in run.copies if copy_run.created_id}
    if not copied:
        return
    try:
        rows = await read_created(
            client,
            account_id=account_id,
            edge="ads",
            object_ids=list(copied),
            fields=READ_FIELDS,
            operation=OPERATION,
        )
    except IntegrationError:
        return
    for ad_id, row in rows.items():
        copied[ad_id].read = row


def _rename_effect(run: CopyRun) -> MetaAdsMutationEffect | None:
    copied_id = run.created_id
    if copied_id is None or not run.plan.renames:
        return None
    if run.rename is not None:
        return run.rename
    fields = freeze_fields(_RENAME_FIELDS)
    # A rename already handed to Meta might have applied; one never sent didn't.
    if run.renaming:
        return MetaAdsMutationEffect(
            fields=fields,
            outcome="unverified",
            error_code="RENAME_NOT_CONFIRMED",
            message="Meta Ads didn't confirm the copy's new name.",
        )
    return MetaAdsMutationEffect(
        fields=fields,
        outcome="failed",
        error_code=NOT_DISPATCHED_CODE,
        message=NOT_DISPATCHED_MESSAGE,
    )


def _parent(run: CopyRun) -> MetaAdsMutationParent:
    rename = _rename_effect(run)
    effects = (ad_effect(run), rename) if rename is not None else (ad_effect(run),)
    return MetaAdsMutationParent(
        identity=(("key", run.plan.key),), decision="submit", effects=effects
    )


def copy_row(run: CopyRun) -> dict[str, Any]:
    """Builds one result row from what the run proved."""
    plan = run.plan
    effect = ad_effect(run)
    observed = dict(effect.fields)
    row = run.read or {}
    rename = _rename_effect(run)
    unexpected = unexpected_changes(run)
    message = effect.message
    if effect.outcome == "applied":
        if rename is not None and rename.outcome != "applied":
            message = _NOT_RENAMED.format(name=plan.source.name)
        elif unexpected:
            message = _UNEXPECTED_CHANGES.format(labels=", ".join(change_labels(unexpected)))
        elif run.read is None:
            message = _READBACK_FAILED
    effective_status = observed.get("effective_status")
    read_name = row.get("name")
    return {
        "source_ad_id": plan.source.ad_id,
        "source_name": plan.source.name or None,
        "name": read_name if isinstance(read_name, str) and read_name else plan.name,
        "adset_id": plan.adset_id,
        "adset_name": plan.adset_name,
        "format": plan.source.format,
        "requested_status": plan.status,
        "paused_for_ai": plan.paused_for_ai,
        "outcome": {"applied": "copied"}.get(effect.outcome, effect.outcome),
        "recovered": observed.get("recovered") == "true",
        "verified": effect.outcome == "applied" and run.read is not None,
        "ad_id": effect.external_ref,
        "effective_status": effective_status,
        "review": review_state(effective_status) if run.read else "unknown",
        "review_reasons": review_reasons(row),
        "unexpected_changes": change_labels(unexpected),
        "preview_url": preview_url(row.get("preview_shareable_link")),
        "error_code": effect.error_code,
        "message": message,
    }
