# apps/api/integrations/google_ads/operations/responsive_search_ads.py

"""Compiles responsive search ads for the build seam and reads back their review state."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .utils import stream_rows

if TYPE_CHECKING:
    from ..tools.schemas.ads import GoogleAdsResponsiveSearchAd

_AD_GROUP_AD = re.compile(r"customers/\d+/adGroupAds/\d+~\d+")


@dataclass(frozen=True, slots=True)
class AdReview:
    """A created ad's live status and where it is in Google's policy review."""

    status: str | None
    review_status: str | None
    approval_status: str | None


def ad_group_ad_body(
    ad: "GoogleAdsResponsiveSearchAd", *, ad_group: str, status: str
) -> dict[str, Any]:
    """Returns the `AdGroupAd` create body for one ad in one ad group."""
    responsive: dict[str, Any] = {
        "headlines": [_text_asset(item.text, item.pin) for item in ad.headlines],
        "descriptions": [_text_asset(item.text, item.pin) for item in ad.descriptions],
    }
    if ad.path1:
        responsive["path1"] = ad.path1
    if ad.path2:
        responsive["path2"] = ad.path2
    body: dict[str, Any] = {"finalUrls": [ad.final_url], "responsiveSearchAd": responsive}
    if ad.mobile_final_url:
        body["finalMobileUrls"] = [ad.mobile_final_url]
    return {"adGroup": ad_group, "status": status, "ad": body}


def _text_asset(text: str, pin: str | None) -> dict[str, str]:
    return {"text": text, "pinnedField": pin} if pin else {"text": text}


async def read_ad_reviews(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    resource_names: Sequence[str],
) -> dict[str, AdReview]:
    """Returns each ad's status and policy review, keyed by its `adGroupAds` resource name."""
    prefix = f"customers/{normalize_customer_id(customer_id)}/"
    wanted = sorted(set(resource_names))
    if any(_AD_GROUP_AD.fullmatch(name) is None or not name.startswith(prefix) for name in wanted):
        raise ValueError("Google Ads ad reviews need this account's ad resource names")
    if not wanted:
        return {}
    names = ", ".join(f"'{name}'" for name in wanted)
    payload = await client.post(
        f"customers/{normalize_customer_id(customer_id)}/googleAds:searchStream",
        operation="read_ad_reviews",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={
            "query": (
                "SELECT ad_group_ad.resource_name, ad_group_ad.status, "  # noqa: S608 -- validated resource names
                "ad_group_ad.policy_summary.review_status, "
                "ad_group_ad.policy_summary.approval_status FROM ad_group_ad "
                f"WHERE ad_group_ad.resource_name IN ({names})"
            )
        },
    )
    reviews: dict[str, AdReview] = {}
    for row in stream_rows(payload, max_rows=len(wanted)):
        item = row.get("adGroupAd")
        if not isinstance(item, Mapping) or item.get("resourceName") not in wanted:
            continue
        policy = item.get("policySummary")
        policy = policy if isinstance(policy, Mapping) else {}
        reviews[str(item["resourceName"])] = AdReview(
            status=_text(item.get("status")),
            review_status=_text(policy.get("reviewStatus")),
            approval_status=_text(policy.get("approvalStatus")),
        )
    return reviews


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
