# apps/api/integrations/meta_ads/operations/create_ads.py

"""Create ads in existing ad sets: one inline creative per ad, sent once, then read back."""

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from core.exceptions.integration import IntegrationError

from ..client import MetaAdsClient
from ..models import MetaAdsPromotedObject
from ..tools.schemas.ads import MediaKey, MetaAdsMediaInput, design_media, media_key
from .ad_rows import AdRun, ad_effect
from .create_objects import MetaCreateLookup, create_object, read_created, validate_create
from .creatives import (
    CreativeCard,
    CreativeDisclaimer,
    CreativeImage,
    CreativeInput,
    CreativeMedia,
    CreativeVideo,
    conversion_domain,
    creative_spec,
)
from .media_source import MediaSource
from .mutations import (
    NOT_DISPATCHED_CODE,
    MetaAdsMutationLedger,
    MetaAdsMutationParent,
)
from .plan_ads import PlannedAd
from .upload_media import MediaUpload, upload_media

_OPERATION = "create_ads"
_CONCURRENCY = 4
_READ_FIELDS = (
    "id,name,status,effective_status,ad_review_feedback,issues_info,preview_shareable_link,"
    "creative{id,degrees_of_freedom_spec,contextual_multi_ads,asset_feed_spec,object_story_spec}"
)
_MEDIA_NOT_UPLOADED = "This ad's image didn't upload, so the ad wasn't sent to Meta."
_STOPPED_BY_DRY_RUN = "Meta rejected another ad in this request, so no ads were created."

type ResolvedMedia = Mapping[MediaKey, CreativeMedia]


def ad_body(
    ad: PlannedAd,
    *,
    page_id: str,
    instagram_user_id: str | None,
    media: ResolvedMedia,
    promoted_object: MetaAdsPromotedObject | None,
) -> dict[str, str]:
    """Builds the form fields for `POST /act_{id}/ads`, status always explicit."""
    body = {
        "name": ad.name,
        "adset_id": ad.adset_id,
        "status": "ACTIVE" if ad.status == "active" else "PAUSED",
        "creative": json.dumps(
            creative_spec(_creative_input(ad, page_id, instagram_user_id, media)),
            separators=(",", ":"),
        ),
    }
    # Meta requires the destination's domain when the campaign shares data with a pixel.
    if promoted_object is not None and promoted_object.pixel_id:
        body["conversion_domain"] = conversion_domain(ad.link)
    return body


def _creative_input(
    ad: PlannedAd, page_id: str, instagram_user_id: str | None, media: ResolvedMedia
) -> CreativeInput:
    design = ad.design

    def resolve(item: MetaAdsMediaInput | None) -> CreativeMedia | None:
        return media[media_key(item)] if item is not None else None

    cards = tuple(
        CreativeCard(
            media=_with_thumbnail(resolve(card.media), resolve(card.thumbnail)),
            headline=card.headline,
            description=card.description,
            link=card.link or ad.link,
            call_to_action=card.call_to_action or ad.call_to_action,
        )
        for card in design.cards or ()
    )
    thumbnail = resolve(design.thumbnail)
    disclaimer = design.disclaimer
    return CreativeInput(
        format=design.format,
        page_id=page_id,
        instagram_user_id=instagram_user_id,
        primary_text=design.primary_text,
        headline=design.headline,
        description=design.description,
        link=ad.link,
        call_to_action=ad.call_to_action,
        url_tags=ad.url_tags,
        media=_with_thumbnail(resolve(design.media), thumbnail),
        # The chosen thumbnail matches the main video; the vertical one keeps Meta's own.
        vertical=resolve(design.vertical_media),
        cards=cards,
        enabled=ad.enabled,
        disclaimer=CreativeDisclaimer(disclaimer.type, disclaimer.text, disclaimer.url)
        if disclaimer
        else None,
    )


def _with_thumbnail(
    item: CreativeMedia | None, thumbnail: CreativeMedia | None
) -> CreativeMedia | None:
    """Puts a chosen thumbnail image on a video; videos already carry Meta's preferred one."""
    if isinstance(item, CreativeVideo) and isinstance(thumbnail, CreativeImage):
        return CreativeVideo(item.video_id, thumbnail_hash=thumbnail.image_hash)
    return item


async def dry_run_ads(
    client: MetaAdsClient, *, account_id: str, bodies: Mapping[int, Mapping[str, str]]
) -> dict[int, str]:
    """Checks each ad with Meta without creating it, four at a time.

    Returns:
        Meta's reason for each rejected ad, by planned index.
    """
    semaphore = asyncio.Semaphore(_CONCURRENCY)
    rejected: dict[int, str] = {}

    async def check(index: int, body: Mapping[str, str]) -> None:
        async with semaphore:
            try:
                reason = await validate_create(
                    client, account_id=account_id, edge="ads", data=body, operation=_OPERATION
                )
            except IntegrationError as exc:
                # An ad Meta couldn't check is never created unchecked.
                reason = f"Meta Ads couldn't check this ad. {exc.user_message}"[:1000]
        if reason is not None:
            rejected[index] = reason

    async with asyncio.TaskGroup() as group:
        for index, body in bodies.items():
            group.create_task(check(index, body))
    return dict(sorted(rejected.items()))


@dataclass
class CreateAdsRun:
    ads: list[AdRun]
    uploads: list[MediaUpload] = field(default_factory=list)
    upload_parents: list[MetaAdsMutationParent] = field(default_factory=list)

    def ledger(self) -> MetaAdsMutationLedger:
        parents = [*self.upload_parents, *(_ad_parent(run) for run in self.ads)]
        return MetaAdsMutationLedger(action="create_ads", parents=tuple(parents))


async def create_ads(
    client: MetaAdsClient,
    *,
    account_id: str,
    scope_label: str,
    planned: Sequence[PlannedAd],
    intent_fields: Mapping[int, Mapping[str, str]],
    sources: Sequence[MediaSource],
    media: ResolvedMedia,
    page_id: str,
    instagram_user_id: str | None,
    promoted_objects: Mapping[str, MetaAdsPromotedObject | None],
    checked: frozenset[int],
) -> CreateAdsRun:
    """Uploads Files, checks unchecked ads with Meta, creates every ad, then reads them back.

    Ads in `checked` already passed Meta's dry run. A dry-run rejection here stops every
    ad before any is created. Later ads continue after one fails.

    Raises:
        asyncio.CancelledError: With a `ledger` attribute: ads being sent are unverified,
            and ads not reached are not dispatched.
    """
    run = CreateAdsRun([AdRun(ad, dict(intent_fields[ad.index])) for ad in planned])
    try:
        resolved = dict(media)
        if sources:
            try:
                run.uploads, upload_ledger = await upload_media(
                    client,
                    account_id=account_id,
                    scope_label=scope_label,
                    sources=sources,
                    poll_seconds=0,
                )
            except (asyncio.CancelledError, Exception) as exc:
                run.upload_parents = _keyed_uploads(getattr(exc, "ledger", None))
                raise
            run.upload_parents = _keyed_uploads(upload_ledger)
            resolved.update(_uploaded_media(run.uploads))
        bodies: dict[int, dict[str, str]] = {}
        for ad_run in run.ads:
            ad = ad_run.ad
            if any(media_key(item) not in resolved for item in design_media(ad.design)):
                ad_run.skip_code, ad_run.skip_message = "MEDIA_NOT_UPLOADED", _MEDIA_NOT_UPLOADED
                continue
            bodies[ad.index] = ad_body(
                ad,
                page_id=page_id,
                instagram_user_id=instagram_user_id,
                media=resolved,
                promoted_object=promoted_objects.get(ad.adset_id),
            )
        unchecked = {index: body for index, body in bodies.items() if index not in checked}
        rejected = await dry_run_ads(client, account_id=account_id, bodies=unchecked)
        if rejected:
            _stop_for_dry_run(run, rejected)
            return run
        await _send_all(client, account_id, run, bodies)
        await _read_back(client, account_id, run)
    except (asyncio.CancelledError, Exception) as exc:
        exc.ledger = run.ledger()
        raise
    return run


def _keyed_uploads(ledger: MetaAdsMutationLedger | None) -> list[MetaAdsMutationParent]:
    """Keys each File's upload alongside the ads, so one ledger accounts for both."""
    if ledger is None:
        return []
    return [
        replace(parent, identity=(("key", f"file:{dict(parent.identity)['file_id']}"),))
        for parent in ledger.parents
    ]


def _uploaded_media(uploads: Sequence[MediaUpload]) -> dict[MediaKey, CreativeMedia]:
    return {
        ("file", upload.file_id): CreativeImage(upload.media_id)
        for upload in uploads
        if upload.outcome == "uploaded" and upload.media_id
    }


def _stop_for_dry_run(run: CreateAdsRun, rejected: Mapping[int, str]) -> None:
    for ad_run in run.ads:
        if ad_run.skip_code is not None:
            continue
        reason = rejected.get(ad_run.ad.index)
        ad_run.skip_code = "DRY_RUN_REJECTED" if reason else NOT_DISPATCHED_CODE
        ad_run.skip_message = reason or _STOPPED_BY_DRY_RUN


async def _send_all(
    client: MetaAdsClient, account_id: str, run: CreateAdsRun, bodies: Mapping[int, dict[str, str]]
) -> None:
    semaphore = asyncio.Semaphore(_CONCURRENCY)

    async def send(ad_run: AdRun) -> None:
        async with semaphore:
            ad = ad_run.ad
            lookup = MetaCreateLookup(
                name=ad.name,
                parent_field="adset.id",
                parent_id=ad.adset_id,
                since=datetime.now(UTC),
            )
            ad_run.sending = True
            ad_run.outcome = await create_object(
                client,
                account_id=account_id,
                edge="ads",
                data=bodies[ad.index],
                operation=_OPERATION,
                lookup=lookup,
            )

    async with asyncio.TaskGroup() as group:
        for ad_run in run.ads:
            if ad_run.ad.index in bodies and ad_run.skip_code is None:
                group.create_task(send(ad_run))


async def _read_back(client: MetaAdsClient, account_id: str, run: CreateAdsRun) -> None:
    """Reads every new ad once; a failed read leaves the ads created but unverified."""
    created = {ad_run.created_id: ad_run for ad_run in run.ads if ad_run.created_id}
    if not created:
        return
    try:
        rows = await read_created(
            client,
            account_id=account_id,
            edge="ads",
            object_ids=list(created),
            fields=_READ_FIELDS,
            operation=_OPERATION,
        )
    except IntegrationError:
        return
    for ad_id, row in rows.items():
        created[ad_id].read = row


def _ad_parent(run: AdRun) -> MetaAdsMutationParent:
    return MetaAdsMutationParent(
        identity=(("key", run.ad.key),), decision="submit", effects=(ad_effect(run),)
    )
