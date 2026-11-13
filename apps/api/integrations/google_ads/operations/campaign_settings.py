# apps/api/integrations/google_ads/operations/campaign_settings.py

"""Reads campaign settings that `google_ads_update_campaigns` changes, in card and API terms."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .asset_automation import AUTOMATION_SWITCHES, automation_on, live_automation, video_pages
from .campaign_bidding import BIDDING_FIELDS, bidding_values, card_bidding
from .utils import stream_rows

type CampaignSetting = Literal[
    "name",
    "start_date",
    "end_date",
    "final_url_suffix",
    "tracking_template",
    "custom_parameters",
    "search_partners",
    "display_expansion",
    "video_pages",
    "final_url_expansion",
    "text_customisation",
    "conversion_goals",
    "bidding",
]

AUTOMATION_PATH = "assetAutomationSettings"
# Each setting's field path in Google's JSON names, as the edit seam compares and masks it.
# Bidding and conversion goals have their own modules; the automation settings share one list.
SETTING_PATHS: dict[CampaignSetting, str] = {
    "name": "name",
    "start_date": "startDateTime",
    "end_date": "endDateTime",
    "final_url_suffix": "finalUrlSuffix",
    "tracking_template": "trackingUrlTemplate",
    "custom_parameters": "urlCustomParameters",
    "search_partners": "networkSettings.targetSearchNetwork",
    "display_expansion": "networkSettings.targetContentNetwork",
    "video_pages": AUTOMATION_PATH,
    "final_url_expansion": AUTOMATION_PATH,
    "text_customisation": AUTOMATION_PATH,
}
_FIELDS = (
    "campaign.resource_name",
    "campaign.id",
    "campaign.name",
    "campaign.status",
    "campaign.advertising_channel_type",
    "campaign.start_date_time",
    "campaign.end_date_time",
    "campaign.final_url_suffix",
    "campaign.tracking_url_template",
    "campaign.url_custom_parameters",
    "campaign.network_settings.target_search_network",
    "campaign.network_settings.target_content_network",
    "campaign.asset_automation_settings",
    *BIDDING_FIELDS,
)


def api_value(setting: CampaignSetting, value: Any) -> Any:
    """Converts a setting from card terms to the value Google stores at its path.

    Dates are whole days in the account time zone. An empty text value, or no end date,
    is null, which clears the field.
    """
    if setting == "start_date":
        return f"{value} 00:00:00"
    if setting == "end_date":
        return None if value is None else f"{value} 23:59:59"
    if setting in {"final_url_suffix", "tracking_template"}:
        return value or None
    if setting == "custom_parameters":
        return [{"key": item["key"], "value": item["value"]} for item in value or ()]
    return value


def card_value(setting: CampaignSetting, value: Any) -> Any:
    """Converts a value Google stores to card terms: dates as `YYYY-MM-DD`, lists never null."""
    if setting in {"start_date", "end_date"}:
        return value[:10] if isinstance(value, str) and value else None
    if setting == "custom_parameters":
        return [
            {"key": str(item.get("key", "")), "value": str(item.get("value", ""))}
            for item in value or ()
            if isinstance(item, Mapping)
        ]
    if setting in {"search_partners", "display_expansion"}:
        return value is True
    if setting == "video_pages":
        return video_pages(value)
    if setting in AUTOMATION_SWITCHES:
        return automation_on(value, AUTOMATION_SWITCHES[setting])
    return value if isinstance(value, str) and value else None


@dataclass(frozen=True, slots=True)
class LiveCampaignSettings:
    resource_name: str
    campaign_id: str
    status: str
    channel: str
    # By setting path, as Google returned them, with absent fields as null or empty.
    values: Mapping[str, Any]

    def settings(self) -> dict[CampaignSetting, Any]:
        return card_settings(self.values)


def card_settings(values: Mapping[str, Any]) -> dict[CampaignSetting, Any]:
    """Every campaign field in card terms, from the values `read_campaign_settings` returns."""
    settings: dict[CampaignSetting, Any] = {
        setting: card_value(setting, values.get(path)) for setting, path in SETTING_PATHS.items()
    }
    settings["bidding"] = card_bidding(values)
    return settings


async def read_campaign_settings(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    campaign_ids: Sequence[str],
) -> dict[str, LiveCampaignSettings]:
    """Returns each campaign's settings by resource name, including removed campaigns.

    Campaigns Google doesn't return are left out.
    """
    if not campaign_ids or not all(item.isdigit() for item in campaign_ids):
        raise ValueError("Google Ads campaign settings reads need campaign IDs")
    ids = ", ".join(sorted(set(campaign_ids)))
    query = f"SELECT {', '.join(_FIELDS)} FROM campaign WHERE campaign.id IN ({ids})"  # noqa: S608 -- digits only
    payload = await client.post(
        f"customers/{normalize_customer_id(customer_id)}/googleAds:searchStream",
        operation="read_campaign_settings",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={"query": query},
    )
    live: dict[str, LiveCampaignSettings] = {}
    for row in stream_rows(payload, max_rows=len(set(campaign_ids))):
        campaign = row.get("campaign")
        if not isinstance(campaign, Mapping):
            continue
        name = campaign.get("resourceName")
        status = campaign.get("status")
        if not isinstance(name, str) or not isinstance(status, str):
            continue
        live[name] = LiveCampaignSettings(
            resource_name=name,
            campaign_id=str(campaign.get("id", "")),
            status=status,
            channel=str(campaign.get("advertisingChannelType", "")),
            values=_values(campaign),
        )
    return live


def _values(campaign: Mapping[str, Any]) -> dict[str, Any]:
    """Each setting path's live value, normalised so equal settings compare equal."""
    networks = campaign.get("networkSettings")
    networks = networks if isinstance(networks, Mapping) else {}
    return {
        "name": campaign.get("name") or None,
        "startDateTime": campaign.get("startDateTime") or None,
        "endDateTime": campaign.get("endDateTime") or None,
        "finalUrlSuffix": campaign.get("finalUrlSuffix") or None,
        "trackingUrlTemplate": campaign.get("trackingUrlTemplate") or None,
        "urlCustomParameters": api_value(
            "custom_parameters",
            card_value("custom_parameters", campaign.get("urlCustomParameters")),
        ),
        # A flag Google leaves out is off.
        "networkSettings.targetSearchNetwork": networks.get("targetSearchNetwork") is True,
        "networkSettings.targetContentNetwork": networks.get("targetContentNetwork") is True,
        AUTOMATION_PATH: live_automation(campaign.get(AUTOMATION_PATH)),
        **bidding_values(campaign),
    }
