# apps/api/integrations/google_ads/operations/performance_max.py

"""Compiles Performance Max campaigns and asset groups for the build seam, and reads live ones."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any, Literal

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .asset_group_state import URL_OPTION_PATHS
from .build import CampaignBuild
from .campaign_settings import api_value
from .conversion_settings import LiveAccountGoal
from .criteria import AUDIENCE_FIELDS
from .search_campaigns import (
    CampaignItem,
    add_campaign_budget,
    add_campaign_locations,
    campaign_body,
)
from .utils import stream_rows

if TYPE_CHECKING:
    from ..tools.schemas.campaigns import GoogleAdsNewPerformanceMaxCampaign
    from ..tools.schemas.performance_max import GoogleAdsNewAssetGroup

type AssetGroupItemKind = Literal[
    "asset_group",
    "listing_filter",
    "text_asset",
    "asset_group_link",
    "search_theme",
    "audience",
    "audience_signal",
]

# Merchant Center links one account holds; far more than any account has.
_MAX_MERCHANT_LINKS = 1_000
# Google allows 100 asset groups in a campaign, so one more shows the read is whole.
_MAX_ASSET_GROUPS_READ = 101


@dataclass(frozen=True, slots=True)
class AssetGroupItem:
    """Which of an asset group's objects a build step came from.

    `content` is the text, asset ID, or theme, so a rejection can name what it was about.
    """

    kind: AssetGroupItemKind
    asset_group: int
    field_type: str | None = None
    content: str | None = None


def add_performance_max_campaign(
    build: CampaignBuild,
    campaign: "GoogleAdsNewPerformanceMaxCampaign",
    *,
    status: str,
    today: date,
    account_goals: Sequence[LiveAccountGoal] = (),
) -> str:
    """Adds the budget, campaign, locations, languages, brand, and goals; returns its name.

    Args:
        account_goals: The account's conversion goals. With `conversion_goals` set, each one
            is set to bid in this campaign or not; Google makes them with the campaign.
    """
    budget = add_campaign_budget(build, campaign.name, campaign.budget.amount_micros)
    body: dict[str, Any] = {
        **campaign_body(campaign, status=status, today=today),
        "advertisingChannelType": "PERFORMANCE_MAX",
        "campaignBudget": budget,
        # The business name and logos then belong to the campaign, not each asset group.
        "brandGuidelinesEnabled": True,
    }
    if not campaign.final_url_expansion:
        body["assetAutomationSettings"] = [
            {
                "assetAutomationType": "FINAL_URL_EXPANSION_TEXT_ASSET_AUTOMATION",
                "assetAutomationStatus": "OPTED_OUT",
            }
        ]
    if campaign.merchant is not None:
        body["shoppingSetting"] = {"merchantId": campaign.merchant.merchant_id}
        if campaign.merchant.feed_label:
            body["shoppingSetting"]["feedLabel"] = campaign.merchant.feed_label
    name = build.create("campaign", body, label=campaign.name, source=CampaignItem("campaign"))
    if name is None:
        raise ValueError("Google Ads builds must name new campaigns")
    add_campaign_locations(build, campaign, name)
    for position, language in enumerate(campaign.languages):
        build.create(
            "campaignCriterion",
            {
                "campaign": name,
                "language": {"languageConstant": f"languageConstants/{language.key}"},
            },
            label=language.name or language.key,
            source=CampaignItem("language", position),
        )
    if campaign.business_name:
        asset = text_asset(build, campaign.business_name, CampaignItem("text_asset"))
        build.create(
            "campaignAsset",
            {"campaign": name, "asset": asset, "fieldType": "BUSINESS_NAME"},
            label=campaign.business_name,
            source=CampaignItem("brand_link", -1),
        )
    for position, logo in enumerate(campaign.logos):
        build.create(
            "campaignAsset",
            {"campaign": name, "asset": logo.asset.resource_name, "fieldType": logo.field_type},
            label=logo.asset.label or logo.asset.asset_id,
            source=CampaignItem("brand_link", position),
        )
    if campaign.conversion_goals is not None:
        _add_goals(build, campaign, name, account_goals)
    return name


def _add_goals(
    build: CampaignBuild,
    campaign: "GoogleAdsNewPerformanceMaxCampaign",
    name: str,
    account_goals: Sequence[LiveAccountGoal],
) -> None:
    chosen = {(goal.category, goal.origin) for goal in campaign.conversion_goals or ()}
    campaign_id = name.rsplit("/", 1)[1]
    for position, goal in enumerate(account_goals):
        build.update(
            "campaignConversionGoal",
            {
                "resourceName": (
                    f"customers/{build.customer_id}/campaignConversionGoals/"
                    f"{campaign_id}~{goal.category}~{goal.origin}"
                ),
                "biddable": (goal.category, goal.origin) in chosen,
            },
            update_mask="biddable",
            label=f"{goal.category} {goal.origin}",
            source=CampaignItem("conversion_goal", position),
        )


def text_asset(build: CampaignBuild, text: str, source: Any) -> str | None:
    """Adds a text asset once per distinct text, however many places use it."""
    return build.create_once(
        f"text:{text}", "asset", {"textAsset": {"text": text}}, label=text, source=source
    )


def add_asset_group(
    build: CampaignBuild,
    group: "GoogleAdsNewAssetGroup",
    *,
    index: int,
    campaign: str,
    status: str,
    retail: bool,
) -> None:
    """Adds an asset group with its URL options, text, images, videos, and search themes.

    Args:
        retail: True for a campaign with a Merchant Center feed, whose groups show every
            product in the feed until listing filters narrow them.
    """
    body: dict[str, Any] = {
        "name": group.name,
        "campaign": campaign,
        "finalUrls": [group.final_url],
        "status": status,
    }
    for setting, value in (group.url_options.requested if group.url_options else {}).items():
        # An empty option on a new group is one it doesn't have.
        if value:
            body[URL_OPTION_PATHS[setting]] = api_value(setting, value)
    name = build.create(
        "assetGroup",
        body,
        label=group.name,
        source=AssetGroupItem("asset_group", index),
    )
    if retail:
        build.create(
            "assetGroupListingGroupFilter",
            {"assetGroup": name, "type": "UNIT_INCLUDED", "listingSource": "SHOPPING"},
            label=f"{group.name}: all products",
            source=AssetGroupItem("listing_filter", index),
        )
    for field_type, texts in (
        ("HEADLINE", group.headlines),
        ("LONG_HEADLINE", group.long_headlines),
        ("DESCRIPTION", group.descriptions),
    ):
        for text in texts:
            asset = text_asset(build, text, AssetGroupItem("text_asset", index, field_type, text))
            _link(
                build,
                name,
                asset,
                field_type,
                text,
                AssetGroupItem("asset_group_link", index, field_type, text),
            )
    for image in group.images:
        asset_id = image.asset.asset_id
        _link(
            build,
            name,
            image.asset.resource_name,
            image.field_type,
            image.asset.label or asset_id,
            AssetGroupItem("asset_group_link", index, image.field_type, asset_id),
        )
    for video in group.videos:
        _link(
            build,
            name,
            video.resource_name,
            "YOUTUBE_VIDEO",
            video.label or video.asset_id,
            AssetGroupItem("asset_group_link", index, "YOUTUBE_VIDEO", video.asset_id),
        )
    for theme in group.search_themes:
        build.create(
            "assetGroupSignal",
            {"assetGroup": name, "searchTheme": {"text": theme}},
            label=theme,
            source=AssetGroupItem("search_theme", index, content=theme),
        )
    if group.audience_signals:
        _add_audience_signal(build, group, name, index)


def _add_audience_signal(
    build: CampaignBuild, group: "GoogleAdsNewAssetGroup", asset_group: str | None, index: int
) -> None:
    """Adds one audience of the group's own holding every segment, so Google reads them as OR."""
    segments = [
        audience_segment(build.customer_id, audience.kind, audience.key)
        for audience in group.audience_signals
    ]
    label = f"{group.name}: audience signal"
    # An asset group's own audience takes no name, and Google removes it with the group.
    audience = build.create(
        "audience",
        {
            "scope": "ASSET_GROUP",
            "assetGroup": asset_group,
            "dimensions": [{"audienceSegments": {"segments": segments}}],
        },
        label=label,
        source=AssetGroupItem("audience", index),
    )
    build.create(
        "assetGroupSignal",
        {"assetGroup": asset_group, "audience": {"audience": audience}},
        label=label,
        source=AssetGroupItem("audience_signal", index),
    )


def audience_segment(customer_id: str, kind: str, key: str) -> dict[str, Any]:
    """Returns one segment of an audience's segment dimension, as Google's JSON names it."""
    field, inner, collection = AUDIENCE_FIELDS[kind]
    return {field: {inner: f"customers/{customer_id}/{collection}/{key}"}}


def _link(
    build: CampaignBuild,
    asset_group: str | None,
    asset: str | None,
    field_type: str,
    label: str,
    source: AssetGroupItem,
) -> None:
    build.create(
        "assetGroupAsset",
        {"assetGroup": asset_group, "asset": asset, "fieldType": field_type},
        label=label,
        source=source,
    )


async def read_merchant_center_ids(
    client: GoogleAdsClient, *, customer_id: str, login_customer_id: str
) -> set[str]:
    """Returns the IDs of the Merchant Center accounts linked to the account."""
    payload = await client.post(
        f"customers/{normalize_customer_id(customer_id)}/googleAds:searchStream",
        operation="read_merchant_center_links",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={
            "query": "SELECT product_link.merchant_center.merchant_center_id FROM product_link "
            "WHERE product_link.type = 'MERCHANT_CENTER'"
        },
    )
    ids = set()
    for row in stream_rows(payload, max_rows=_MAX_MERCHANT_LINKS):
        link = row.get("productLink") or {}
        merchant = str((link.get("merchantCenter") or {}).get("merchantCenterId") or "")
        if merchant.isdigit():
            ids.add(merchant)
    return ids


@dataclass(frozen=True, slots=True)
class PerformanceMaxCampaignFacts:
    """A live campaign's channel, brand placement, feed, and the names of its asset groups."""

    name: str
    channel: str
    # False when the business name and logos belong to each asset group, not the campaign.
    brand_guidelines: bool
    merchant_id: str | None
    asset_group_names: tuple[str, ...]


async def read_performance_max_campaign(
    client: GoogleAdsClient, *, customer_id: str, login_customer_id: str, campaign_id: str
) -> PerformanceMaxCampaignFacts | None:
    """Returns the campaign's facts, or None when it's removed or doesn't exist."""
    if not campaign_id.isdigit():
        raise ValueError("Google Ads campaign ids must contain only digits")
    path = f"customers/{normalize_customer_id(customer_id)}/googleAds:searchStream"
    campaigns = await client.post(
        path,
        operation="read_performance_max_campaign",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={
            "query": (
                "SELECT campaign.id, campaign.name, campaign.advertising_channel_type, "  # noqa: S608 -- digit-only id
                "campaign.brand_guidelines_enabled, campaign.shopping_setting.merchant_id "
                f"FROM campaign WHERE campaign.id = {campaign_id} AND campaign.status != 'REMOVED'"
            )
        },
    )
    rows = stream_rows(campaigns, max_rows=1)
    campaign = rows[0].get("campaign") if rows else None
    if not isinstance(campaign, dict):
        return None
    groups = await client.post(
        path,
        operation="read_performance_max_campaign",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={
            "query": (
                "SELECT asset_group.id, asset_group.name FROM asset_group "  # noqa: S608 -- digit-only id
                f"WHERE campaign.id = {campaign_id} AND asset_group.status != 'REMOVED' "
                f"ORDER BY asset_group.id LIMIT {_MAX_ASSET_GROUPS_READ}"
            )
        },
    )
    merchant = str((campaign.get("shoppingSetting") or {}).get("merchantId") or "")
    return PerformanceMaxCampaignFacts(
        name=str(campaign.get("name") or f"Campaign {campaign_id}"),
        channel=str(campaign.get("advertisingChannelType") or ""),
        brand_guidelines=campaign.get("brandGuidelinesEnabled") is True,
        merchant_id=merchant if merchant.isdigit() and merchant != "0" else None,
        asset_group_names=tuple(
            str(row["assetGroup"]["name"])
            for row in stream_rows(groups, max_rows=_MAX_ASSET_GROUPS_READ)
            if isinstance(row.get("assetGroup"), dict) and row["assetGroup"].get("name")
        ),
    )
