# apps/api/integrations/meta_ads/tools/utils/ad_preparation.py

"""Re-reads everything ad creation depends on, then has Meta check each ad before approval."""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import ModelRetry, RunContext

from core.exceptions.integration import IntegrationError
from services.agents.runtime.context import RuntimeDeps
from services.integrations.approved_display_args import proposed_args
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.entity_references import resolve_runtime_references
from services.integrations.files import FileReference
from services.integrations.report_results import ReportResultBudget

from ...client import MetaAdsClient
from ...creative_features import has_ai_generated
from ...entity_resolvers.utils import MAX_EXACT_REFERENCES, account_currency, asset_read_args
from ...operations.create_ads import ad_body, dry_run_ads
from ...operations.creatives import CreativeImage, CreativeMedia, CreativeVideo
from ...operations.list_assets import (
    POST_SCAN_LIMIT,
    VIDEO_SCAN_LIMIT,
    find_post_references,
    find_video_references,
    preferred_thumbnail,
    read_image_references,
    read_instagram_references,
    read_page_references,
)
from ...operations.list_objects import list_objects, read_objects_by_id
from ...operations.media_source import MediaSource, require_pinned, resolve_media_source
from ...operations.plan_ads import (
    PlannedAd,
    design_problem,
    duplicate_name,
    intent_fields,
    plan_ads,
)
from ...operations.values import require_currency
from ...references import MetaAdsAdSetReference, MetaAdsMediaReference
from ..schemas.ads import (
    UPLOAD_VIDEOS_FIRST,
    MediaKey,
    MetaAdsCreateAdsRequest,
    SharedAdSettings,
    design_media,
    follow_shared,
    media_key,
)
from ..schemas.launch import MetaAdsLaunchCampaignRequest
from ..schemas.objects import UNDELETED_AD_STATUSES, MetaAdsObject
from .create_operation import validated

_OPERATION = "create_ads"
MAX_ADS_PER_AD_SET = 50
_MAX_LISTED_PROBLEMS = 5


@dataclass
class Prepared:
    planned: list[PlannedAd]
    sources: list[MediaSource]
    media: dict[MediaKey, CreativeMedia]
    promoted_objects: dict[str, Any]
    created_off_for_ai: bool
    intent_fields: dict[int, dict[str, str]] = field(default_factory=dict)
    # Ads Meta already checked with a dry run; the rest are checked after their Files upload.
    checked: frozenset[int] = frozenset()


async def hydrate_references(
    deps: RuntimeDeps, entity_kind: str, field_key: str, references: Sequence[Any]
) -> list[dict[str, Any]]:
    """Re-reads references through their resolver for the approval card, 50 at a time."""
    # A resolver takes at most 50 references at once; one call can use more media than that.
    hydrated: list[dict[str, Any]] = []
    for start in range(0, len(references), MAX_EXACT_REFERENCES):
        hydrated.extend(
            await resolve_runtime_references(
                deps,
                entity_kind=entity_kind,
                field_key=field_key,
                values=[
                    reference.model_dump(mode="json")
                    for reference in references[start : start + MAX_EXACT_REFERENCES]
                ],
            )
        )
    return hydrated


def ads_as_reviewed(
    ctx: RunContext[RuntimeDeps],
    model: type[MetaAdsCreateAdsRequest | MetaAdsLaunchCampaignRequest],
    ads: list[Any],
) -> list[Any]:
    """Returns the ads as the card showed them: unedited ones follow the shared settings they copy."""
    # Card edits start from `follow_shared`, so only ads left as proposed still hold copies.
    proposed = proposed_args(ctx)
    try:
        unedited = validated(model, proposed).ads == ads
    except ModelRetry:
        return ads
    return follow_shared(proposed) if unedited else ads


def required_currency(entry: ResolvedContextEntry) -> str:
    return require_currency(account_currency(entry), operation=_OPERATION)


def distinct_ad_sets(request: MetaAdsCreateAdsRequest) -> dict[str, MetaAdsAdSetReference]:
    return {reference.adset_id: reference for design in request.ads for reference in design.ad_sets}


def distinct_media(request: SharedAdSettings) -> dict[MediaKey, Any]:
    return {media_key(item): item for design in request.ads for item in design_media(design)}


def require_ready_videos(request: SharedAdSettings) -> None:
    """Refuses a library video Meta is still processing, so the agent waits for it."""
    for item in distinct_media(request).values():
        if (
            isinstance(item, MetaAdsMediaReference)
            and item.media_type == "video"
            and item.media_status != "ready"
        ):
            raise ModelRetry(
                f"The video {item.label} isn't ready. List the account's videos and use it "
                "once its media_status is ready."
            )


def check_designs(request: MetaAdsCreateAdsRequest, ad_sets: Mapping[str, Any]) -> None:
    raise_design_problems(
        request, [[ad_sets.get(ref.adset_id) for ref in design.ad_sets] for design in request.ads]
    )


def raise_design_problems(request: SharedAdSettings, ad_sets: Sequence[Sequence[Any]]) -> None:
    """Refuses the call with the first few designs that don't fit their ad sets."""
    problems = [
        f"{design.name}: {problem}"
        for design, facts in zip(request.ads, ad_sets, strict=True)
        if (problem := design_problem(design, request, facts))
    ]
    if problems:
        raise ModelRetry(" ".join(problems[:_MAX_LISTED_PROBLEMS]))


async def resolve_sources(deps: RuntimeDeps, request: SharedAdSettings) -> list[MediaSource]:
    """Checks each workspace File against Meta's image policy; Files can only be images."""
    sources: list[MediaSource] = []
    for item in distinct_media(request).values():
        if not isinstance(item, FileReference):
            continue
        source = await resolve_media_source(deps.db, workspace=deps.workspace, reference=item)
        if source.media_type != "image":
            raise ModelRetry(f"{source.file.name} is a video. {UPLOAD_VIDEOS_FIRST}")
        sources.append(source)
    return sources


async def prepare(
    deps: RuntimeDeps,
    client: MetaAdsClient,
    entry: ResolvedContextEntry,
    request: MetaAdsCreateAdsRequest,
    reviewed: Mapping[str, Any],
) -> Prepared:
    """Re-reads everything the ads depend on, then asks Meta to check each ad."""
    account_id = entry.external_id
    live = await _live_ad_sets(client, entry, request)
    check_designs(request, live)
    media, sources = await read_ad_inputs(deps, client, entry, request, reviewed)
    planned = plan_ads(request, {adset_id: item.name for adset_id, item in live.items()})
    await _check_capacity(client, entry, planned)
    promoted = {adset_id: item.promoted_object for adset_id, item in live.items()}
    bodies = {
        ad.index: ad_body(
            ad,
            page_id=request.page.page_id,
            instagram_user_id=request.instagram_user_id,
            media=media,
            promoted_object=promoted.get(ad.adset_id),
        )
        for ad in planned
        if not any(isinstance(item, FileReference) for item in design_media(ad.design))
    }
    rejected = await dry_run_ads(client, account_id=account_id, bodies=bodies)
    if rejected:
        names = {ad.index: ad.name for ad in planned}
        reasons = " ".join(
            f"{names[index]}: {reason}"
            for index, reason in list(rejected.items())[:_MAX_LISTED_PROBLEMS]
        )
        raise ModelRetry(f"Meta Ads rejected these ads, so none were created. {reasons}")
    return Prepared(
        planned=planned,
        sources=sources,
        media=media,
        promoted_objects=promoted,
        created_off_for_ai=has_ai_generated(request.automatic_changes or ()),
        intent_fields={ad.index: intent_fields(ad) for ad in planned},
        checked=frozenset(bodies),
    )


async def read_ad_inputs(
    deps: RuntimeDeps,
    client: MetaAdsClient,
    entry: ResolvedContextEntry,
    request: SharedAdSettings,
    reviewed: Mapping[str, Any],
) -> tuple[dict[MediaKey, CreativeMedia], list[MediaSource]]:
    """Re-reads the Page, Instagram account, posts, and library media, and checks File pins."""
    await _check_identities(client, entry, request)
    await _check_posts(client, entry, request)
    media = await _library_media(client, entry, request)
    sources = await resolve_sources(deps, request)
    pinned = {
        str(item.get("file_id")): item
        for item in reviewed.get("_files") or ()
        if isinstance(item, Mapping)
    }
    for source in sources:
        # A File the agent proposed must be the revision shown; one chosen on the card is
        # uploaded as it is when the operator approves.
        if str(source.file.id) in pinned:
            require_pinned(source, pinned[str(source.file.id)])
    return media, sources


async def _live_ad_sets(
    client: MetaAdsClient, entry: ResolvedContextEntry, request: MetaAdsCreateAdsRequest
) -> dict[str, MetaAdsObject]:
    ids = list(distinct_ad_sets(request))
    live = await read_objects_by_id(
        client,
        account_id=entry.external_id,
        object_type="adset",
        object_ids=ids,
        currency=required_currency(entry),
    )
    if set(ids) - set(live):
        raise ModelRetry(
            "Some selected ad sets are no longer in this ad account. Choose them again."
        )
    return live


async def _check_identities(
    client: MetaAdsClient, entry: ResolvedContextEntry, request: SharedAdSettings
) -> None:
    """Confirms the ad account can still advertise as the Page and Instagram account."""
    read_args = asset_read_args(entry, ReportResultBudget("meta_ads", _OPERATION))
    pages, _more = await read_page_references(client, **read_args)
    if request.page.page_id not in {page.page_id for page in pages}:
        raise ModelRetry(
            f"This ad account can't advertise as the Page {request.page.label}. Choose a Page "
            "from meta_ads_list_assets."
        )
    account = request.instagram_account
    if account is None:
        return
    accounts, _more = await read_instagram_references(client, **read_args)
    if account.instagram_user_id not in {item.instagram_user_id for item in accounts}:
        raise ModelRetry(
            f"The Instagram account {account.label} isn't connected to this ad account. "
            "Choose one from meta_ads_list_assets."
        )


async def _check_posts(
    client: MetaAdsClient, entry: ResolvedContextEntry, request: SharedAdSettings
) -> None:
    """Re-reads each post through its Page or Instagram account, and its boost eligibility."""
    posts = {design.post.key: design.post for design in request.ads if design.post is not None}
    if not posts:
        return
    read_args = asset_read_args(entry, ReportResultBudget("meta_ads", _OPERATION))
    live = {
        post.key: post
        for post in await find_post_references(client, **read_args, references=list(posts.values()))
    }
    if set(posts) - set(live):
        raise ModelRetry(
            f"A post isn't among the {POST_SCAN_LIMIT} most recent posts of a Page or Instagram "
            "account this ad account can use. List posts with meta_ads_list_assets and choose "
            "again."
        )
    if any(post.boostable is False for post in live.values()):
        raise ModelRetry(
            "Meta no longer allows an Instagram post to run as an ad. Choose another post."
        )


async def _library_media(
    client: MetaAdsClient, entry: ResolvedContextEntry, request: SharedAdSettings
) -> dict[MediaKey, CreativeMedia]:
    """Confirms library images exist and videos are ready, and reads video thumbnails."""
    items = [
        item for item in distinct_media(request).values() if isinstance(item, MetaAdsMediaReference)
    ]
    read_args = asset_read_args(entry, ReportResultBudget("meta_ads", _OPERATION))
    media = await _library_images(
        client, read_args, sorted({i.image_hash for i in items if i.image_hash})
    )
    media.update(
        await _library_videos(
            client, entry, read_args, sorted({i.video_id for i in items if i.video_id})
        )
    )
    _require_video_thumbnails(request, media)
    return media


async def _library_images(
    client: MetaAdsClient, read_args: Mapping[str, Any], hashes: Sequence[str]
) -> dict[MediaKey, CreativeMedia]:
    if not hashes:
        return {}
    images, _more = await read_image_references(client, **read_args, hashes=hashes)
    if missing := set(hashes) - {image.image_hash for image in images}:
        raise ModelRetry(
            f"{len(missing)} image(s) are no longer in this ad account's media library. "
            "Choose them again from meta_ads_list_assets."
        )
    return {
        ("image", image.image_hash or ""): CreativeImage(image.image_hash or "") for image in images
    }


async def _library_videos(
    client: MetaAdsClient,
    entry: ResolvedContextEntry,
    read_args: Mapping[str, Any],
    video_ids: Sequence[str],
) -> dict[MediaKey, CreativeMedia]:
    if not video_ids:
        return {}
    videos = {
        video.video_id: video
        for video in await find_video_references(client, **read_args, video_ids=video_ids)
    }
    media: dict[MediaKey, CreativeMedia] = {}
    for video_id in video_ids:
        video = videos.get(video_id)
        if video is None:
            raise ModelRetry(
                f"A video isn't among the {VIDEO_SCAN_LIMIT} most recent videos in this ad "
                "account's media library. Upload it again with meta_ads_upload_media."
            )
        if video.media_status != "ready":
            raise ModelRetry(
                "A video isn't ready in this ad account's media library. List the account's "
                "videos and use it once its media_status is ready."
            )
        try:
            thumbnail = await preferred_thumbnail(
                client, account_id=entry.external_id, video_id=video_id
            )
        except IntegrationError:
            # Only matters when no thumbnail was chosen, which is checked next.
            thumbnail = None
        media[("video", video_id)] = CreativeVideo(video_id, thumbnail_url=thumbnail)
    return media


def _require_video_thumbnails(
    request: SharedAdSettings, media: Mapping[MediaKey, CreativeMedia]
) -> None:
    """Instagram needs a thumbnail for every video; fail when neither one was chosen nor found."""

    def has_thumbnail(item: Any, chosen: Any) -> bool:
        video = media.get(media_key(item)) if item is not None else None
        return (
            not isinstance(video, CreativeVideo) or chosen is not None or bool(video.thumbnail_url)
        )

    for design in request.ads:
        uses = [(design.media, design.thumbnail), (design.vertical_media, None)]
        uses.extend((card.media, card.thumbnail) for card in design.cards or ())
        if not all(has_thumbnail(item, chosen) for item, chosen in uses):
            raise ModelRetry(f"{design.name}: add a thumbnail image for the video.")


async def existing_ads(
    client: MetaAdsClient, entry: ResolvedContextEntry, adset_ids: Sequence[str]
) -> tuple[dict[str, int], dict[str, set[str]]]:
    """Counts the undeleted ads in each ad set and collects their names, casefolded."""
    existing = await list_objects(
        client,
        account_id=entry.external_id,
        object_type="ad",
        statuses=UNDELETED_AD_STATUSES,
        adset_ids=list(adset_ids),
        limit=MAX_ADS_PER_AD_SET * len(adset_ids),
        currency=required_currency(entry),
    )
    if existing.truncated:
        raise ModelRetry(
            "These ad sets hold too many ads to check against Meta's limit. Use fewer ad sets "
            "in one call."
        )
    names: dict[str, set[str]] = defaultdict(set)
    counts: dict[str, int] = defaultdict(int)
    for item in existing.objects:
        if item.adset_id:
            counts[item.adset_id] += 1
            names[item.adset_id].add((item.name or "").casefold())
    return counts, names


def over_capacity(counts: Mapping[str, int], labels: Mapping[str, str]) -> None:
    """Refuses the call when any ad set would hold more than Meta's 50 ads."""
    if full := [adset_id for adset_id, count in counts.items() if count > MAX_ADS_PER_AD_SET]:
        raise ModelRetry(
            f"Meta allows {MAX_ADS_PER_AD_SET} ads per ad set, and {labels[full[0]]} would "
            "go over. Add fewer ads there, or delete ads it no longer needs."
        )


async def _check_capacity(
    client: MetaAdsClient, entry: ResolvedContextEntry, planned: Sequence[PlannedAd]
) -> None:
    """Keeps each ad set within Meta's 50 ads, and each new name unique in its ad set."""
    adset_ids = sorted({ad.adset_id for ad in planned})
    counts, names = await existing_ads(client, entry, adset_ids)
    for ad in planned:
        counts[ad.adset_id] += 1
    over_capacity(counts, {ad.adset_id: ad.adset_name or ad.adset_id for ad in planned})
    if name := duplicate_name(planned, names):
        raise ModelRetry(f"An ad called {name} is already in its ad set. Choose another name.")
