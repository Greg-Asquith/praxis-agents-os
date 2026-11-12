# apps/api/integrations/google_ads/tools/utils/performance_max_builds.py

"""Rules, account reads, and dry run answers for building Performance Max campaigns and groups."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

from ...client import GoogleAdsClient
from ...operations.assets import MAX_ASSET_LOOKUP, list_assets
from ...operations.build import BuildProblem, CampaignBuild, dry_run_build
from ...operations.conversion_settings import LiveAccountGoal, goal_name, read_account_goals
from ...operations.media import image_fits
from ...operations.performance_max import (
    AssetGroupItem,
    add_asset_group,
    add_performance_max_campaign,
    read_merchant_center_ids,
)
from ...operations.search_campaigns import CampaignItem
from ...operations.search_targeting import read_audiences, read_languages, read_locations
from ..schemas.campaigns import performance_max_brand_problems
from ..schemas.performance_max import asset_group_problems

if TYPE_CHECKING:
    from ..schemas.campaigns import (
        GoogleAdsCreateCampaignRequest,
        GoogleAdsNewPerformanceMaxCampaign,
    )
    from ..schemas.performance_max import GoogleAdsNewAssetGroup

_OPERATION = "create_campaign"


@dataclass(frozen=True, slots=True)
class AccountFacts:
    """What the account holds that the campaign depends on."""

    merchant_ids: frozenset[str]
    goals: tuple[LiveAccountGoal, ...]


def performance_max_problems(
    request: "GoogleAdsCreateCampaignRequest", customer_id: str | None
) -> list[str]:
    """Why Google would refuse the brand or an asset group, before reading the account."""
    campaign = request.campaign
    problems = performance_max_brand_problems(campaign, request.asset_groups)
    retail = campaign.merchant is not None
    for group in request.asset_groups:
        problems.extend(asset_group_problems(group, retail=retail))
    if campaign.conversion_goals == []:
        problems.append("Choose at least one conversion goal, or use the account's goals.")
    if customer_id and any(
        reference.customer_id != customer_id for reference in _media(campaign, request.asset_groups)
    ):
        problems.append(MEDIA_FROM_ANOTHER_ACCOUNT)
    return problems


MEDIA_FROM_ANOTHER_ACCOUNT = "Choose images and videos from the account the campaign is in."


def group_media(groups: Sequence["GoogleAdsNewAssetGroup"]) -> list[Any]:
    """The asset groups' image and video references."""
    return [
        *(image.asset for group in groups for image in group.images),
        *(video for group in groups for video in group.videos),
    ]


def audience_id(kind: str, key: str) -> str:
    return f"{kind}:{key}"


async def read_signal_audiences(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    groups: Sequence["GoogleAdsNewAssetGroup"],
) -> dict[str, str]:
    """Returns the name of each audience signal that exists, by `kind:key`."""
    keys: dict[str, list[str]] = {}
    for group in groups:
        for audience in group.audience_signals:
            keys.setdefault(audience.kind, []).append(audience.key)
    if not keys:
        return {}
    found = await read_audiences(
        client, customer_id=customer_id, login_customer_id=login_customer_id, keys=keys
    )
    return {audience_id(kind, key): option.name for (kind, key), option in found.items()}


def unknown_audiences(
    groups: Sequence["GoogleAdsNewAssetGroup"], audiences: dict[str, str]
) -> list[str]:
    """The `kind:key` of each audience signal the account doesn't have, once each."""
    ids = (
        audience_id(audience.kind, audience.key)
        for group in groups
        for audience in group.audience_signals
    )
    return sorted({item for item in ids if item not in audiences})


def _media(
    campaign: "GoogleAdsNewPerformanceMaxCampaign", groups: Sequence["GoogleAdsNewAssetGroup"]
) -> list[Any]:
    return [*(logo.asset for logo in campaign.logos), *group_media(groups)]


async def read_account_facts(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    campaign: "GoogleAdsNewPerformanceMaxCampaign",
    with_goals: bool = False,
) -> AccountFacts:
    """Reads linked Merchant Center accounts and account goals, when the campaign needs them.

    Args:
        with_goals: Also reads the goals when the campaign keeps the account's, for the card.
    """
    merchant_ids: set[str] = set()
    if campaign.merchant is not None:
        merchant_ids = await read_merchant_center_ids(
            client, customer_id=customer_id, login_customer_id=login_customer_id
        )
    goals: tuple[LiveAccountGoal, ...] = ()
    if with_goals or campaign.conversion_goals is not None:
        read = await read_account_goals(
            client, customer_id=customer_id, login_customer_id=login_customer_id
        )
        goals = tuple(sorted(read.values(), key=lambda goal: goal.resource_name))
    return AccountFacts(frozenset(merchant_ids), goals)


def account_problems(
    campaign: "GoogleAdsNewPerformanceMaxCampaign", facts: AccountFacts
) -> list[str]:
    """Why the account can't take the campaign's feed or goals."""
    problems = []
    if campaign.merchant is not None and campaign.merchant.merchant_id not in facts.merchant_ids:
        problems.append(
            f"Merchant Center account {campaign.merchant.merchant_id} isn't linked to this "
            "Google Ads account. Link it in Google Ads, or leave the product feed out."
        )
    known = {(goal.category, goal.origin) for goal in facts.goals}
    problems.extend(
        f"{goal_name(goal.category, goal.origin)} isn't one of the account's conversion goals."
        for goal in campaign.conversion_goals or ()
        if (goal.category, goal.origin) not in known
    )
    return problems


def compile_performance_max(
    build: CampaignBuild,
    request: "GoogleAdsCreateCampaignRequest",
    campaign: "GoogleAdsNewPerformanceMaxCampaign",
    today: date,
    indexes: Sequence[int],
    goals: Sequence[LiveAccountGoal],
) -> None:
    name = add_performance_max_campaign(
        build, campaign, status=request.status, today=today, account_goals=goals
    )
    for index in indexes:
        add_asset_group(
            build,
            request.asset_groups[index],
            index=index,
            campaign=name,
            status=request.status,
            retail=campaign.merchant is not None,
        )


async def read_images(
    client: GoogleAdsClient, *, customer_id: str, login_customer_id: str, asset_ids: list[str]
) -> dict[str, dict[str, Any]]:
    """Reads each image's name and size, and the shapes it fits."""
    images: dict[str, dict[str, Any]] = {}
    batch = MAX_ASSET_LOOKUP - 1
    for start in range(0, len(asset_ids), batch):
        ids = asset_ids[start : start + batch]
        for asset in await list_assets(
            client,
            customer_id=customer_id,
            login_customer_id=login_customer_id,
            asset_ids=ids,
            limit=len(ids),
        ):
            if asset.asset_type != "IMAGE" or asset.size is None:
                continue
            width, height = asset.size
            images[asset.resource_name.rsplit("/", 1)[1]] = {
                "name": asset.name,
                "width": width,
                "height": height,
                "fits": image_fits(width, height)[0],
            }
    return images


async def performance_max_checks(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    request: "GoogleAdsCreateCampaignRequest",
    today: date,
) -> dict[str, Any]:
    """Reads what the card names and checks, then dry runs everything the card can't fault."""
    campaign = request.campaign
    locations = await read_locations(
        client,
        customer_id=customer_id,
        login_customer_id=login_customer_id,
        keys=[item.key for item in (*campaign.locations, *campaign.excluded_locations)],
    )
    languages = {
        option.key: option.name
        for option in await read_languages(
            client, customer_id=customer_id, login_customer_id=login_customer_id
        )
    }
    image_ids = sorted(
        {reference.asset_id for reference in _media(campaign, request.asset_groups)}
        - {video.asset_id for group in request.asset_groups for video in group.videos}
    )
    images = await read_images(
        client, customer_id=customer_id, login_customer_id=login_customer_id, asset_ids=image_ids
    )
    audiences = await read_signal_audiences(
        client,
        customer_id=customer_id,
        login_customer_id=login_customer_id,
        groups=request.asset_groups,
    )
    facts = await read_account_facts(
        client,
        customer_id=customer_id,
        login_customer_id=login_customer_id,
        campaign=campaign,
        with_goals=True,
    )
    answers: dict[str, list[Any]] = {
        "campaign_problems": [],
        "problems": [],
        "request_problems": [],
    }
    # Google's answer would only repeat a problem the card already shows.
    if not performance_max_problems(request, customer_id) and not account_problems(campaign, facts):
        answers = await _dry_run(
            client,
            customer_id=customer_id,
            login_customer_id=login_customer_id,
            request=request,
            today=today,
            known={
                "locations": set(locations),
                "languages": set(languages),
                "images": images,
                "audiences": audiences,
            },
            goals=facts.goals,
        )
    every_location = (*campaign.locations, *campaign.excluded_locations)
    return {
        "unavailable": False,
        "today": today.isoformat(),
        "locations": {key: option.name for key, option in locations.items()},
        "unknown_locations": [item.key for item in every_location if item.key not in locations],
        "languages": {
            item.key: languages[item.key] for item in campaign.languages if item.key in languages
        },
        "unknown_languages": [item.key for item in campaign.languages if item.key not in languages],
        "images": images,
        "unknown_images": [asset_id for asset_id in image_ids if asset_id not in images],
        "audiences": audiences,
        "unknown_audiences": unknown_audiences(request.asset_groups, audiences),
        "merchant_ids": sorted(facts.merchant_ids),
        "account_goals": [
            {
                "category": goal.category,
                "origin": goal.origin,
                "name": goal_name(goal.category, goal.origin),
                "biddable": goal.values.get("biddable") is True,
            }
            for goal in facts.goals
        ],
        **answers,
    }


def dry_run_ready(group: "GoogleAdsNewAssetGroup", known: dict[str, Any]) -> bool:
    """True when the card faults none of the group's images or audiences, so Google checks it."""
    images, audiences = known["images"], known["audiences"]
    return all(
        image.field_type in images.get(image.asset.asset_id, {}).get("fits", ())
        for image in group.images
    ) and all(
        audience_id(audience.kind, audience.key) in audiences for audience in group.audience_signals
    )


async def _dry_run(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    request: "GoogleAdsCreateCampaignRequest",
    today: date,
    known: dict[str, Any],
    goals: Sequence[LiveAccountGoal],
) -> dict[str, list[Any]]:
    """Returns Google's rejections, leaving out what the card already faults."""
    campaign = request.campaign
    checked = campaign.model_copy(
        update={
            "locations": [item for item in campaign.locations if item.key in known["locations"]],
            "excluded_locations": [
                item for item in campaign.excluded_locations if item.key in known["locations"]
            ],
            "languages": [item for item in campaign.languages if item.key in known["languages"]],
        }
    )
    build = CampaignBuild(customer_id)
    indexes = [
        index for index, group in enumerate(request.asset_groups) if dry_run_ready(group, known)
    ]
    compile_performance_max(build, request, checked, today, indexes, goals)
    answers: dict[str, list[Any]] = {
        "campaign_problems": [],
        "problems": [],
        "request_problems": [],
    }
    for problem in await dry_run_build(
        client,
        build,
        login_customer_id=login_customer_id,
        operation=_OPERATION,
        partial_failure=False,
    ):
        _sort_answer(answers, problem, request, checked, goals)
    return answers


def _sort_answer(
    answers: dict[str, list[Any]],
    problem: BuildProblem,
    request: "GoogleAdsCreateCampaignRequest",
    campaign: "GoogleAdsNewPerformanceMaxCampaign",
    goals: Sequence[LiveAccountGoal],
) -> None:
    message = f"Google says: {problem.message}"
    source = problem.step.source if problem.step is not None else None
    if isinstance(source, AssetGroupItem):
        answers["problems"].append(asset_group_answer(request.asset_groups, source, message))
    elif isinstance(source, CampaignItem):
        answers["campaign_problems"].append(
            {**campaign_item_fields(campaign, source, goals), "message": message}
        )
    else:
        answers["request_problems"].append(message)


def asset_group_answer(
    groups: Sequence["GoogleAdsNewAssetGroup"], source: AssetGroupItem, message: str
) -> dict[str, Any]:
    """Names Google's rejection by group, kind, and content, so an edit can tell it's gone."""
    return {
        "asset_group": groups[source.asset_group].name,
        "kind": source.kind,
        "field_type": source.field_type,
        "content": source.content,
        "message": message,
    }


def campaign_item_fields(
    campaign: "GoogleAdsNewPerformanceMaxCampaign",
    source: CampaignItem,
    goals: Sequence[LiveAccountGoal],
) -> dict[str, Any]:
    """Names a rejected campaign item by its content, so an edit can tell it's gone."""
    fields: dict[str, Any] = {"kind": source.kind}
    if source.kind == "location":
        fields["key"] = campaign.locations[source.position].key
    elif source.kind == "excluded_location":
        fields["key"] = campaign.excluded_locations[source.position].key
    elif source.kind == "language":
        fields["key"] = campaign.languages[source.position].key
    elif source.kind == "brand_link":
        # The business name's link has no position among the logos.
        fields["key"] = (
            campaign.logos[source.position].asset.asset_id
            if source.position >= 0
            else "business_name"
        )
    elif source.kind == "conversion_goal":
        goal = goals[source.position]
        fields["key"] = f"{goal.category}~{goal.origin}"
    return fields
