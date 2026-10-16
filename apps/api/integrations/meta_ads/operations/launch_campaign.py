# apps/api/integrations/meta_ads/operations/launch_campaign.py

"""Build a campaign, its ad sets, and their ads in one go, then turn it on when asked.

Everything is created paused but the ads, and the campaign is turned on last, so nothing
delivers until the whole build is created and confirmed. A confirmed rejection fails that
object and skips what depends on it; an unclear create, a throttle, or the deadline stops
the build. Nothing is deleted after a failure.
"""

import asyncio
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Literal

from core.exceptions.integration import IntegrationError, IntegrationRateLimitError
from services.audit_events import IntegrationOperationIntent, IntegrationOperationIntentGroup

from ..client import MetaAdsClient
from ..creative_features import has_ai_generated
from ..tools.schemas.ads import MediaKey, design_media, media_key
from ..tools.schemas.launch import MetaAdsLaunchCampaignRequest
from .ad_rows import AdRun, ad_effect, unexpected_changes
from .create_ad_set import (
    AdSetPlan,
    AdSetRun,
    AdSetTerms,
    PlannedAdSet,
    campaign_problems,
    plan_ad_set,
    planned_ad_set,
)
from .create_ads import (
    ad_body,
    keyed_uploads,
    read_back_ads,
    send_ads,
    upload_intent_group,
    uploaded_media,
)
from .create_campaign import CampaignPlan, CampaignRun, planned_campaign
from .create_objects import MetaCreateLookup, MetaCreateResult, create_object, validate_create
from .creatives import CreativeMedia
from .list_objects import read_objects_by_id
from .media_source import MediaSource
from .mutations import (
    NOT_DISPATCHED_CODE,
    NOT_DISPATCHED_MESSAGE,
    MetaAdsMutationEffect,
    MetaAdsMutationLedger,
    MetaAdsMutationParent,
    freeze_fields,
)
from .plan_ads import PlannedAd, design_problem, intent_fields, place_ads
from .update_status import MetaAdsStatusTarget, update_status
from .upload_media import MediaUpload, upload_media

OPERATION = "launch_campaign"
TURN_ON_CAMPAIGN_KEY = "turn_on:campaign"
_CONCURRENCY = 4
_THROTTLED = IntegrationRateLimitError.__name__
_TURN_ON_FIELDS = {"requested_status": "ACTIVE"}
_CAMPAIGN_NOT_CREATED = "The campaign wasn't created, so this wasn't sent to Meta."
_AD_SET_NOT_CREATED = "This ad's ad set wasn't created, so the ad wasn't sent to Meta."
_OUT_OF_TIME = (
    "The build ran out of time, so the rest wasn't sent to Meta. Ask the agent to finish it "
    "with the step tools."
)
_UNCONFIRMED = "Meta Ads didn't confirm part of the build, so it stopped. Check Ads Manager."
_HELD_FOR_FAILURES = "Not turned on, because part of the campaign wasn't built or confirmed."
_HELD_FOR_CHANGES = (
    "Not turned on, because Meta turned on automatic changes you left off. Check the ads in "
    "Ads Manager."
)
_HELD_FOR_AD_SETS = "Not turned on, because an ad set didn't turn on."
_HELD_UNFINISHED = "Not turned on, because the build didn't finish."

type LaunchStop = Literal["unverified", "throttled", "deadline"]
# Live: on and waiting for Meta's review. Partial: something failed, and nothing is on.
type LaunchState = Literal["live", "paused", "partial", "stopped"]


def turn_on_key(key: str) -> str:
    return f"turn_on:ad_set:{key}"


def launch_problems(request: MetaAdsLaunchCampaignRequest) -> list[str]:
    """Checks each ad set against the new campaign and each ad against its new ad sets."""
    campaign = planned_campaign(request.campaign)
    problems = [
        f"{ad_set.name}: {problem}"
        for ad_set in request.ad_sets
        for problem in campaign_problems(ad_set, campaign)
    ]
    facts = {ad_set.key: planned_ad_set(ad_set) for ad_set in request.ad_sets}
    problems.extend(
        f"{ad.name}: {problem}"
        for ad in request.ads
        if (problem := design_problem(ad, request, [facts[key] for key in ad.ad_set_keys]))
    )
    return problems


@dataclass(frozen=True, slots=True)
class LaunchAdSet:
    key: str
    # The body gains the campaign's ID once the campaign is created.
    plan: AdSetPlan
    facts: PlannedAdSet


@dataclass(frozen=True, slots=True)
class LaunchPlan:
    """The approved build as Meta will receive it, in creation order."""

    campaign: CampaignPlan
    ad_sets: tuple[LaunchAdSet, ...]
    # Each ad's `adset_id` holds its ad set's key until the ad set exists.
    ads: tuple[PlannedAd, ...]
    ad_fields: Mapping[int, Mapping[str, str]]
    sources: tuple[MediaSource, ...]
    # Library images and ready videos, read at preparation.
    media: Mapping[MediaKey, CreativeMedia]
    page_id: str
    instagram_user_id: str | None
    go_live: bool
    created_off_for_ai: bool


def plan_launch(
    request: MetaAdsLaunchCampaignRequest,
    *,
    campaign: CampaignPlan,
    currency: str,
    terms: Mapping[str, AdSetTerms],
    sources: Sequence[MediaSource],
    media: Mapping[MediaKey, CreativeMedia],
) -> LaunchPlan:
    """Plans every ad set and ad from the request and what preparation read."""
    facts = planned_campaign(request.campaign)
    ad_sets = tuple(
        LaunchAdSet(
            key=ad_set.key,
            plan=plan_ad_set(
                ad_set,
                facts,
                campaign_id=None,
                currency=currency,
                start_time=terms[ad_set.key].start_time,
                end_time=terms[ad_set.key].end_time,
                eu=terms[ad_set.key].eu,
                object_store_url=terms[ad_set.key].object_store_url,
                key=f"ad_set:{ad_set.key}",
            ),
            facts=planned_ad_set(ad_set),
        )
        for ad_set in request.ad_sets
    )
    names = {ad_set.key: ad_set.name for ad_set in request.ad_sets}
    slots = [[(key, names[key]) for key in ad.ad_set_keys] for ad in request.ads]
    ads = place_ads(request, slots, status="active" if request.go_live else "paused")
    return LaunchPlan(
        campaign=campaign,
        ad_sets=ad_sets,
        ads=tuple(ads),
        ad_fields={ad.index: _ad_fields(ad) for ad in ads},
        sources=tuple(sources),
        media=dict(media),
        page_id=request.page.page_id,
        instagram_user_id=request.instagram_user_id,
        go_live=request.go_live,
        created_off_for_ai=has_ai_generated(request.automatic_changes or ()),
    )


def _ad_fields(ad: PlannedAd) -> dict[str, str]:
    fields = {key: value for key, value in intent_fields(ad).items() if key != "adset_id"}
    return {**fields, "ad_set_key": ad.adset_id}


def launch_intent_groups(plan: LaunchPlan) -> list[IntegrationOperationIntentGroup]:
    """Records every object the launch may create or turn on, keyed as its ledger is."""
    groups = [
        IntegrationOperationIntentGroup(
            key="campaigns:create",
            action="create_campaign",
            entity_type="meta_ads_campaign",
            items=[IntegrationOperationIntent(fields=plan.campaign.intent_fields)],
        ),
        IntegrationOperationIntentGroup(
            key="adsets:create",
            action="create_ad_set",
            entity_type="meta_ads_ad_set",
            items=[
                IntegrationOperationIntent(fields=item.plan.intent_fields) for item in plan.ad_sets
            ],
        ),
    ]
    if plan.sources:
        groups.append(upload_intent_group(plan.sources))
    groups.append(
        IntegrationOperationIntentGroup(
            key="ads:create",
            action="create_ad",
            entity_type="meta_ads_ad",
            fields={
                "page_id": plan.page_id,
                "instagram_user_id": plan.instagram_user_id,
                "created_off_for_ai": plan.created_off_for_ai,
            },
            items=[IntegrationOperationIntent(fields=plan.ad_fields[ad.index]) for ad in plan.ads],
        )
    )
    if plan.go_live:
        groups.extend(
            [
                IntegrationOperationIntentGroup(
                    key="adsets:turn_on",
                    action="update_status",
                    entity_type="meta_ads_ad_set",
                    items=[
                        IntegrationOperationIntent(
                            fields={"key": turn_on_key(item.key), **_TURN_ON_FIELDS}
                        )
                        for item in plan.ad_sets
                    ],
                ),
                IntegrationOperationIntentGroup(
                    key="campaigns:turn_on",
                    action="update_status",
                    entity_type="meta_ads_campaign",
                    items=[
                        IntegrationOperationIntent(
                            fields={"key": TURN_ON_CAMPAIGN_KEY, **_TURN_ON_FIELDS}
                        )
                    ],
                ),
            ]
        )
    return groups


@dataclass
class LaunchRun:
    """What the build proved so far, object by object, in creation order."""

    plan: LaunchPlan
    campaign: CampaignRun
    ad_sets: list[AdSetRun]
    ads: list[AdRun]
    uploads: list[MediaUpload] = field(default_factory=list)
    upload_parents: list[MetaAdsMutationParent] = field(default_factory=list)
    # Activation outcomes by ledger key.
    turned_on: dict[str, MetaAdsMutationParent] = field(default_factory=dict)
    held: str | None = None
    stopped: LaunchStop | None = None
    stop_message: str | None = None

    @classmethod
    def start(cls, plan: LaunchPlan) -> "LaunchRun":
        return cls(
            plan=plan,
            campaign=CampaignRun(dict(plan.campaign.intent_fields)),
            ad_sets=[AdSetRun(dict(item.plan.intent_fields)) for item in plan.ad_sets],
            ads=[AdRun(ad, dict(plan.ad_fields[ad.index])) for ad in plan.ads],
        )

    @property
    def live(self) -> bool:
        parent = self.turned_on.get(TURN_ON_CAMPAIGN_KEY)
        return parent is not None and parent.outcome == "applied"

    @property
    def state(self) -> LaunchState:
        if self.stopped == "unverified":
            return "stopped"
        if self.live:
            return "live"
        if self.stopped is None and _all_confirmed(self) and not self.plan.go_live:
            return "paused"
        return "partial"

    def stop(self, reason: LaunchStop, message: str) -> None:
        self.stopped = reason
        self.stop_message = message[:1000]

    def ads_in(self, key: str) -> list[AdRun]:
        return [run for run in self.ads if run.fields["ad_set_key"] == key]

    def ledger(self) -> MetaAdsMutationLedger:
        parents = [
            _create_parent(self.campaign),
            *(_create_parent(run) for run in self.ad_sets),
            *(self.upload_parents or [_unsent_upload(source) for source in self.plan.sources]),
            *(_create_parent(run) for run in self.ads),
        ]
        if self.plan.go_live:
            keys = [turn_on_key(item.key) for item in self.plan.ad_sets]
            parents.extend(
                self.turned_on.get(key) or _held_parent(key, self.held or _HELD_UNFINISHED)
                for key in (*keys, TURN_ON_CAMPAIGN_KEY)
            )
        return MetaAdsMutationLedger(action=OPERATION, parents=tuple(parents))


async def launch_campaign(
    client: MetaAdsClient,
    *,
    account_id: str,
    currency: str,
    scope_label: str,
    plan: LaunchPlan,
    deadline: float,
) -> LaunchRun:
    """Creates the campaign, each ad set, the uploads, and the ads, then turns it on if asked.

    The campaign was dry-run at preparation; each ad set and ad is dry-run here once its
    parent exists. No new step starts after `deadline`, a `time.monotonic()` value.

    Raises:
        asyncio.CancelledError: With a `ledger` attribute: the object in flight is
            unverified once sent, and objects not reached are not dispatched.
    """
    run = LaunchRun.start(plan)
    try:
        await _build(client, account_id, currency, scope_label, run, deadline)
    except (asyncio.CancelledError, Exception) as exc:
        exc.ledger = run.ledger()
        raise
    return run


async def _build(
    client: MetaAdsClient,
    account_id: str,
    currency: str,
    scope_label: str,
    run: LaunchRun,
    deadline: float,
) -> None:
    await _create_all(client, account_id, scope_label, run, deadline)
    # A partial build is read back too, so the step tools can finish it; a throttle would refuse.
    if run.stopped != "throttled":
        await _read_back(client, account_id, currency, run)
    if run.plan.go_live and run.stopped is None and not _out_of_time(run, deadline):
        await _turn_on(client, account_id, currency, run)


async def _create_all(
    client: MetaAdsClient, account_id: str, scope_label: str, run: LaunchRun, deadline: float
) -> None:
    """Creates each level in order, stopping where the build must stop."""
    if not await _create_campaign(client, account_id, run):
        return
    for index in range(len(run.ad_sets)):
        if _out_of_time(run, deadline) or not await _create_ad_set(client, account_id, run, index):
            return
    if _out_of_time(run, deadline) or not await _upload(client, account_id, scope_label, run):
        return
    for item in run.plan.ad_sets:
        if _out_of_time(run, deadline) or not await _create_ads(client, account_id, run, item):
            return


def _out_of_time(run: LaunchRun, deadline: float) -> bool:
    if time.monotonic() < deadline:
        return False
    run.stop("deadline", _OUT_OF_TIME)
    return True


async def _create_campaign(client: MetaAdsClient, account_id: str, run: LaunchRun) -> bool:
    """Creates the campaign; returns whether the build continues."""
    body = run.plan.campaign.body
    campaign = run.campaign
    campaign.sending = True
    campaign.outcome = await create_object(
        client,
        account_id=account_id,
        edge="campaigns",
        data=body,
        operation=OPERATION,
        lookup=MetaCreateLookup(name=body["name"], since=datetime.now(UTC)),
    )
    if not _settled(run, campaign.outcome):
        return False
    if (campaign_id := campaign.outcome.object_id) is None:
        for item in (*run.ad_sets, *run.ads):
            item.skip_code, item.skip_message = "CAMPAIGN_NOT_CREATED", _CAMPAIGN_NOT_CREATED
        return False
    for ad_set in run.ad_sets:
        ad_set.fields["campaign_id"] = campaign_id
    return True


async def _create_ad_set(
    client: MetaAdsClient, account_id: str, run: LaunchRun, index: int
) -> bool:
    """Dry-runs, then creates, one ad set; returns whether the build continues."""
    item = run.plan.ad_sets[index]
    ad_set = run.ad_sets[index]
    campaign_id = ad_set.fields["campaign_id"]
    body = item.plan.with_campaign(campaign_id).body
    try:
        reason = await _dry_run(client, account_id, "adsets", body)
    except IntegrationRateLimitError as exc:
        ad_set.skip_code, ad_set.skip_message = "RATE_LIMITED", exc.user_message[:1000]
        run.stop("throttled", exc.user_message)
        return False
    if reason is None:
        ad_set.sending = True
        ad_set.outcome = await create_object(
            client,
            account_id=account_id,
            edge="adsets",
            data=body,
            operation=OPERATION,
            lookup=MetaCreateLookup(
                name=body["name"],
                parent_field="campaign.id",
                parent_id=campaign_id,
                since=datetime.now(UTC),
            ),
        )
        if not _settled(run, ad_set.outcome):
            return False
    else:
        ad_set.skip_code, ad_set.skip_message = "DRY_RUN_REJECTED", reason
    created_id = ad_set.outcome.object_id if ad_set.outcome else None
    for ad_run in run.ads_in(item.key):
        if created_id is None:
            ad_run.skip_code, ad_run.skip_message = "AD_SET_NOT_CREATED", _AD_SET_NOT_CREATED
        else:
            ad_run.ad = replace(ad_run.ad, adset_id=created_id)
            ad_run.fields["adset_id"] = created_id
    return True


async def _upload(client: MetaAdsClient, account_id: str, scope_label: str, run: LaunchRun) -> bool:
    """Uploads the Files that ads still to be created use; returns whether the build continues."""
    needed = {
        media_key(item)
        for ad_run in run.ads
        if ad_run.skip_code is None
        for item in design_media(ad_run.ad.design)
    }
    sources = [source for source in run.plan.sources if ("file", str(source.file.id)) in needed]
    if not sources:
        return True
    try:
        run.uploads, ledger = await upload_media(
            client, account_id=account_id, scope_label=scope_label, sources=sources, poll_seconds=0
        )
    except (asyncio.CancelledError, Exception) as exc:
        run.upload_parents = _with_unsent(run, keyed_uploads(getattr(exc, "ledger", None)))
        raise
    run.upload_parents = _with_unsent(run, keyed_uploads(ledger))
    effects = [upload.effect for upload in run.uploads if upload.effect is not None]
    if any(effect.outcome == "unverified" for effect in effects):
        run.stop("unverified", _UNCONFIRMED)
        return False
    if throttled := next((e for e in effects if e.error_code == _THROTTLED), None):
        run.stop("throttled", throttled.message or "")
        return False
    return True


def _with_unsent(
    run: LaunchRun, parents: Sequence[MetaAdsMutationParent]
) -> list[MetaAdsMutationParent]:
    """Accounts for Files no remaining ad needed, so they were never uploaded."""
    sent = {parent.identity: parent for parent in parents}
    return [
        sent.get((("key", f"file:{source.file.id}"),)) or _unsent_upload(source)
        for source in run.plan.sources
    ]


async def _create_ads(
    client: MetaAdsClient, account_id: str, run: LaunchRun, item: LaunchAdSet
) -> bool:
    """Dry-runs every ad in one ad set, then creates those Meta accepted."""
    media = {**run.plan.media, **uploaded_media(run.uploads)}
    runs = [ad_run for ad_run in run.ads_in(item.key) if ad_run.skip_code is None]
    bodies: dict[int, dict[str, str]] = {}
    for ad_run in runs:
        if any(media_key(media_item) not in media for media_item in design_media(ad_run.ad.design)):
            ad_run.skip_code = "MEDIA_NOT_UPLOADED"
            ad_run.skip_message = "This ad's image didn't upload, so the ad wasn't sent to Meta."
            continue
        bodies[ad_run.ad.index] = ad_body(
            ad_run.ad,
            page_id=run.plan.page_id,
            instagram_user_id=run.plan.instagram_user_id,
            media=media,
            promoted_object=item.facts.promoted_object,
        )
    try:
        rejected = await _dry_run_ads(client, account_id, bodies)
    except IntegrationRateLimitError as exc:
        run.stop("throttled", exc.user_message)
        return False
    for ad_run in runs:
        if reason := rejected.get(ad_run.ad.index):
            ad_run.skip_code, ad_run.skip_message = "DRY_RUN_REJECTED", reason
    await send_ads(client, account_id, runs, bodies)
    outcomes = [ad_run.outcome for ad_run in runs if ad_run.outcome is not None]
    return all(_settled(run, outcome) for outcome in outcomes)


async def _dry_run(
    client: MetaAdsClient, account_id: str, edge: Literal["ads", "adsets"], body: Mapping[str, str]
) -> str | None:
    """Returns Meta's reason to refuse the create; a throttle raises, since it stops the build."""
    try:
        return await validate_create(
            client, account_id=account_id, edge=edge, data=body, operation=OPERATION
        )
    except IntegrationRateLimitError:
        raise
    except IntegrationError as exc:
        # An object Meta couldn't check is never created unchecked.
        return f"Meta Ads couldn't check this. {exc.user_message}"[:1000]


async def _dry_run_ads(
    client: MetaAdsClient, account_id: str, bodies: Mapping[int, Mapping[str, str]]
) -> dict[int, str]:
    semaphore = asyncio.Semaphore(_CONCURRENCY)
    rejected: dict[int, str] = {}

    async def check(index: int, body: Mapping[str, str]) -> None:
        async with semaphore:
            if reason := await _dry_run(client, account_id, "ads", body):
                rejected[index] = reason

    try:
        async with asyncio.TaskGroup() as group:
            for index, body in bodies.items():
                group.create_task(check(index, body))
    except* IntegrationRateLimitError as errors:
        raise errors.exceptions[0] from None
    return rejected


def _settled(run: LaunchRun, outcome: MetaCreateResult) -> bool:
    """Stops the build on an unclear create or a throttle; other outcomes let it go on."""
    if outcome.status == "unverified":
        run.stop("unverified", _UNCONFIRMED)
        return False
    if outcome.status == "failed" and outcome.error_code == _THROTTLED:
        run.stop("throttled", outcome.message or "")
        return False
    return True


async def _read_back(client: MetaAdsClient, account_id: str, currency: str, run: LaunchRun) -> None:
    """Reads every created object, one listing per level; a failed read leaves it unconfirmed."""
    for object_type, runs in (("campaign", [run.campaign]), ("adset", run.ad_sets)):
        created = {
            outcome.object_id: item
            for item in runs
            if (outcome := item.outcome) and outcome.status == "applied" and outcome.object_id
        }
        if not created:
            continue
        try:
            found = await read_objects_by_id(
                client,
                account_id=account_id,
                object_type=object_type,
                object_ids=list(created),
                currency=currency,
            )
        except IntegrationError:
            continue
        for object_id, item in created.items():
            if read := found.get(object_id):
                item.created = read
                item.read = {"effective_status": read.effective_status}
    await read_back_ads(client, account_id, run.ads)


async def _turn_on(client: MetaAdsClient, account_id: str, currency: str, run: LaunchRun) -> None:
    """Turns on every ad set, then the campaign last, once everything was built and confirmed."""
    if not _all_confirmed(run):
        run.held = _HELD_FOR_FAILURES
        return
    if any(unexpected_changes(ad_run) for ad_run in run.ads):
        run.held = _HELD_FOR_CHANGES
        return
    keys = {
        ad_set.created.id: turn_on_key(item.key)
        for item, ad_set in zip(run.plan.ad_sets, run.ad_sets, strict=True)
        if ad_set.created is not None
    }
    targets = [
        MetaAdsStatusTarget("adset", before=ad_set.created)
        for ad_set in run.ad_sets
        if ad_set.created is not None
    ]
    await _change_status(client, account_id, currency, run, targets, keys)
    if any(run.turned_on[key].outcome != "applied" for key in keys.values()):
        run.held = _HELD_FOR_AD_SETS
        return
    campaign = run.campaign.created
    if campaign is not None:
        target = MetaAdsStatusTarget("campaign", before=campaign)
        await _change_status(
            client, account_id, currency, run, [target], {campaign.id: TURN_ON_CAMPAIGN_KEY}
        )


async def _change_status(
    client: MetaAdsClient,
    account_id: str,
    currency: str,
    run: LaunchRun,
    targets: Sequence[MetaAdsStatusTarget],
    keys: Mapping[str, str],
) -> None:
    """Turns the targets on and records each outcome under its launch key."""
    try:
        ledger, _stale = await update_status(
            client, account_id=account_id, currency=currency, targets=targets, status="ACTIVE"
        )
    except asyncio.CancelledError as exc:
        _record_turned_on(run, getattr(exc, "ledger", None), keys)
        raise
    _record_turned_on(run, ledger, keys)


def _record_turned_on(
    run: LaunchRun, ledger: MetaAdsMutationLedger | None, keys: Mapping[str, str]
) -> None:
    for parent in ledger.parents if ledger else ():
        key = keys[dict(parent.identity)["object_id"]]
        run.turned_on[key] = replace(parent, identity=(("key", key),))


def _all_confirmed(run: LaunchRun) -> bool:
    """Checks whether every object was created and read back, and every File uploaded."""
    created = (run.campaign, *run.ad_sets, *run.ads)
    uploads_ok = all(upload.outcome == "uploaded" for upload in run.uploads)
    return uploads_ok and all(
        ad_effect(item).outcome == "applied" and item.read is not None for item in created
    )


def _create_parent(run: CampaignRun | AdSetRun | AdRun) -> MetaAdsMutationParent:
    return MetaAdsMutationParent(
        identity=(("key", run.fields["key"]),), decision="submit", effects=(ad_effect(run),)
    )


def _unsent_upload(source: MediaSource) -> MetaAdsMutationParent:
    return _failed_parent(
        f"file:{source.file.id}",
        {"media_type": source.media_type},
        NOT_DISPATCHED_CODE,
        NOT_DISPATCHED_MESSAGE,
    )


def _held_parent(key: str, message: str) -> MetaAdsMutationParent:
    return _failed_parent(key, _TURN_ON_FIELDS, "NOT_TURNED_ON", message)


def _failed_parent(
    key: str, fields: Mapping[str, str], error_code: str, message: str
) -> MetaAdsMutationParent:
    return MetaAdsMutationParent(
        identity=(("key", key),),
        decision="submit",
        effects=(
            MetaAdsMutationEffect(
                fields=freeze_fields(fields),
                outcome="failed",
                error_code=error_code,
                message=message,
            ),
        ),
    )
