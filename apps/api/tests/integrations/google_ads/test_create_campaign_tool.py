# apps/api/tests/integrations/google_ads/test_create_campaign_tool.py

"""Building a Search campaign: one atomic request, the serving rules, the dry run, and evidence."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry

from core.exceptions.integration import IntegrationFailureDisposition, IntegrationValidationError
from integrations.google_ads.tools import create_campaign as tool_module
from integrations.google_ads.tools.schemas.campaigns import (
    GoogleAdsCreateCampaignOutput,
    GoogleAdsCreateCampaignRequest,
)
from integrations.google_ads.tools.utils.accounts import approval_accounts
from services.audit_events import AuditStatus
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.google_ads.support import _writable_google_ads_entry

_C = "customers/111"
_KNOWN_LOCATIONS = {"2826": "United Kingdom", "1006886": "London"}
# Image assets by ID: a landscape image, a square one that also fits as a logo.
_IMAGES = {
    "301": {"widthPixels": 1200, "heightPixels": 628},
    "302": {"widthPixels": 1200, "heightPixels": 1200},
}


class _Account:
    """One account: answers location, feed, goal, and image reads, and applies mutates."""

    def __init__(
        self,
        *,
        reject_location: str | None = None,
        refuse_send: bool = False,
        merchant_ids: tuple[str, ...] = (),
    ):
        self.reject_location = reject_location
        self.refuse_send = refuse_send
        self.merchant_ids = merchant_ids
        self.mutates: list[dict[str, Any]] = []

    async def post(self, _path: str, **kwargs: Any) -> Any:
        body = kwargs["json"]
        if "query" in body:
            return [{"results": self._rows(body["query"])}]
        self.mutates.append(body)
        if self.refuse_send and not body["validateOnly"]:
            raise IntegrationValidationError(
                "A campaign with this name already exists.",
                failure_disposition=IntegrationFailureDisposition.REJECTED,
            )
        responses, errors = [], []
        for index, operation in enumerate(body["mutateOperations"]):
            key = next(iter(operation))
            resource = key.removesuffix("Operation")
            created = operation[key].get("create") or operation[key]["update"]
            location = created.get("location", {}).get("geoTargetConstant", "")
            if self.reject_location and location.endswith(f"/{self.reject_location}"):
                responses.append({})
                errors.append(
                    {
                        "message": "This location can't be targeted.",
                        "errorCode": {"criterionError": "INVALID_GEO_TARGET"},
                        "location": {
                            "fieldPathElements": [
                                {"fieldName": "mutate_operations", "index": index}
                            ]
                        },
                    }
                )
                continue
            collection = {
                "campaignBudget": "campaignBudgets/700",
                "campaign": "campaigns/800",
                "campaignCriterion": f"campaignCriteria/800~{index}",
                "adGroup": f"adGroups/{900 + index}",
                "adGroupCriterion": f"adGroupCriteria/{900 + index}~{index}",
                "adGroupAd": f"adGroupAds/{900 + index}~{index}",
                "asset": f"assets/{500 + index}",
                "campaignAsset": f"campaignAssets/800~{500 + index}~SITELINK",
                "adGroupAsset": f"adGroupAssets/{900 + index}~{500 + index}~CALLOUT",
                "assetGroup": "assetGroups/950",
                "assetGroupAsset": f"assetGroupAssets/950~{500 + index}~HEADLINE",
                "assetGroupSignal": f"assetGroupSignals/950~{index}",
                "assetGroupListingGroupFilter": f"assetGroupListingGroupFilters/950~{index}",
                "campaignConversionGoal": "campaignConversionGoals/800~PURCHASE~WEBSITE",
            }[resource]
            responses.append({f"{resource}Result": {"resourceName": f"{_C}/{collection}"}})
        reply: dict[str, Any] = {"mutateOperationResponses": responses}
        if errors:
            reply["partialFailureError"] = {"details": [{"errors": errors}]}
        return reply

    def _rows(self, query: str) -> list[dict[str, Any]]:
        if "FROM product_link" in query:
            return [
                {"productLink": {"merchantCenter": {"merchantCenterId": merchant}}}
                for merchant in self.merchant_ids
            ]
        if "FROM customer_conversion_goal" in query:
            return [
                {
                    "customerConversionGoal": {
                        "resourceName": f"{_C}/customerConversionGoals/{category}~WEBSITE",
                        "category": category,
                        "origin": "WEBSITE",
                        "biddable": True,
                    }
                }
                for category in ("PURCHASE", "SIGNUP")
            ]
        if "FROM asset " in query:
            return [
                {"asset": {"id": asset_id, "type": "IMAGE", "imageAsset": {"fullSize": size}}}
                for asset_id, size in _IMAGES.items()
                if asset_id in query
            ]
        if "FROM language_constant" in query:
            return [{"languageConstant": {"id": "1000", "name": "English", "code": "en"}}]
        return [
            {"geoTargetConstant": {"id": key, "name": name}}
            for key, name in _KNOWN_LOCATIONS.items()
            if key in query
        ]


def _ad() -> dict[str, Any]:
    return {
        "headlines": [{"text": "Hiking Boots"}, {"text": "Free Returns"}, {"text": "Waterproof"}],
        "descriptions": [{"text": "Boots for every trail."}, {"text": "Free UK delivery."}],
        "final_url": "https://shop.test/boots",
    }


def _ad_group(**over: Any) -> dict[str, Any]:
    return {
        "name": "Waterproof Boots",
        "keywords": [{"text": "waterproof hiking boots", "match_type": "EXACT"}],
        "ads": [_ad()],
        **over,
    }


def _campaign(**over: Any) -> dict[str, Any]:
    return {
        "name": "Hiking Boots UK",
        "budget": {"kind": "new", "daily_amount": "60"},
        "bidding": {"strategy": "MAXIMIZE_CONVERSIONS", "target_cpa": "18.00"},
        "locations": [{"key": "2826", "name": "United Kingdom"}],
        **over,
    }


def _entry():
    entry = _writable_google_ads_entry()
    metadata = {**entry.permissions_metadata, "currency_code": "GBP", "time_zone": "Europe/London"}
    return replace(entry, permissions_metadata=metadata)


def _ctx(entry):
    return SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(entry,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name="google_ads_create_campaign",
        tool_call_id="create-campaign-call",
    )


async def _display(monkeypatch, account: _Account, args: dict[str, Any]) -> dict[str, Any]:
    monkeypatch.setattr(
        tool_module, "google_ads_client_for_principal", AsyncMock(return_value=account)
    )
    deps = SimpleNamespace(
        db=None,
        user=None,
        workspace=None,
        active_context=ResolvedActiveContext(entries=(_entry(),)),
    )
    return await tool_module._approval_display_args(deps, args)


async def _run(monkeypatch, account: _Account, args: dict[str, Any], *, approved_entry=None):
    entry = _entry()
    monkeypatch.setattr(tool_module, "google_ads_client", AsyncMock(return_value=account))
    monkeypatch.setattr(
        tool_module,
        "approved_display_args",
        lambda _ctx: {"_accounts": approval_accounts([approved_entry or entry])},
    )
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    request = GoogleAdsCreateCampaignRequest.model_validate(args)
    result = await tool_module.google_ads_create_campaign(
        _ctx(entry), request.campaign, request.ad_groups, request.asset_groups, request.status
    )
    return result, audit


async def test_one_atomic_request_builds_the_campaign_parents_first_with_temporary_names(
    monkeypatch,
) -> None:
    account = _Account()
    start = datetime.now(UTC).date() + timedelta(days=30)
    args = {
        "campaign": _campaign(
            excluded_locations=[{"key": "1006886", "name": "London"}],
            negative_keywords=[{"text": "cheap", "match_type": "BROAD"}],
            start_date=start.isoformat(),
            end_date=(start + timedelta(days=10)).isoformat(),
        ),
        "ad_groups": [_ad_group()],
    }

    result, audit = await _run(monkeypatch, account, args)

    sent = account.mutates[-1]
    assert sent["validateOnly"] is False and sent["partialFailure"] is False
    budget, campaign, group = (
        f"{_C}/campaignBudgets/-1",
        f"{_C}/campaigns/-2",
        f"{_C}/adGroups/-3",
    )
    operations = sent["mutateOperations"]
    assert [next(iter(operation)) for operation in operations] == [
        "campaignBudgetOperation",
        "campaignOperation",
        "campaignCriterionOperation",
        "campaignCriterionOperation",
        "campaignCriterionOperation",
        "adGroupOperation",
        "adGroupCriterionOperation",
        "adGroupAdOperation",
    ]
    assert operations[0]["campaignBudgetOperation"]["create"] == {
        "name": "Hiking Boots UK",
        "amountMicros": "60000000",
        "deliveryMethod": "STANDARD",
        "explicitlyShared": False,
        "period": "DAILY",
        "resourceName": budget,
    }
    assert operations[1]["campaignOperation"]["create"] == {
        "name": "Hiking Boots UK",
        "status": "PAUSED",
        "advertisingChannelType": "SEARCH",
        "campaignBudget": budget,
        "networkSettings": {
            "targetGoogleSearch": True,
            "targetSearchNetwork": False,
            "targetContentNetwork": False,
            "targetPartnerSearchNetwork": False,
        },
        "geoTargetTypeSetting": {"positiveGeoTargetType": "PRESENCE"},
        "containsEuPoliticalAdvertising": "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING",
        "maximizeConversions": {"targetCpaMicros": "18000000"},
        "startDateTime": f"{start.isoformat()} 00:00:00",
        "endDateTime": f"{(start + timedelta(days=10)).isoformat()} 23:59:59",
        "resourceName": campaign,
    }
    assert [operation["campaignCriterionOperation"]["create"] for operation in operations[2:5]] == [
        {"campaign": campaign, "location": {"geoTargetConstant": "geoTargetConstants/2826"}},
        {
            "campaign": campaign,
            "location": {"geoTargetConstant": "geoTargetConstants/1006886"},
            "negative": True,
        },
        {
            "campaign": campaign,
            "negative": True,
            "keyword": {"text": "cheap", "matchType": "BROAD"},
        },
    ]
    assert operations[5]["adGroupOperation"]["create"]["campaign"] == campaign
    assert operations[6]["adGroupCriterionOperation"]["create"]["adGroup"] == group
    data = GoogleAdsCreateCampaignOutput.model_validate(result).results[0].data
    assert data.outcome == "created"
    assert (data.campaign.campaign_id, data.campaign.campaign_budget_id) == ("800", "700")
    assert data.ad_groups[0].reference.campaign_id == "800"
    assert [(row.kind, row.created) for row in data.kinds] == [
        ("budget", 1),
        ("campaign", 1),
        ("location", 1),
        ("excluded_location", 1),
        ("ad_group", 1),
        ("keyword", 1),
        ("negative_keyword", 1),
        ("ad", 1),
    ]
    assert audit.await_args.kwargs["status"] == AuditStatus.SUCCESS


async def test_a_sitelink_on_the_campaign_and_an_ad_group_is_created_once_and_linked_to_both(
    monkeypatch,
) -> None:
    account = _Account()
    sitelink = {"type": "sitelink", "link_text": "Boot Sale", "final_url": "https://shop.test/sale"}
    args = {
        "campaign": _campaign(assets=[sitelink]),
        "ad_groups": [
            _ad_group(
                assets=[
                    {**sitelink, "link_text": " Boot  Sale"},
                    {"type": "callout", "text": "Free Returns"},
                ]
            )
        ],
    }

    result, _audit = await _run(monkeypatch, account, args)

    operations = account.mutates[-1]["mutateOperations"]
    created = {
        key.removesuffix("Operation"): [op[key]["create"] for op in operations if key in op]
        for key in ("assetOperation", "campaignAssetOperation", "adGroupAssetOperation")
    }
    sitelink_name, callout_name = f"{_C}/assets/-3", f"{_C}/assets/-5"
    assert created["asset"] == [
        {
            "sitelinkAsset": {"linkText": "Boot Sale"},
            "finalUrls": ["https://shop.test/sale"],
            "resourceName": sitelink_name,
        },
        {"calloutAsset": {"calloutText": "Free Returns"}, "resourceName": callout_name},
    ]
    assert created["campaignAsset"] == [
        {"campaign": f"{_C}/campaigns/-2", "asset": sitelink_name, "fieldType": "SITELINK"}
    ]
    assert created["adGroupAsset"] == [
        {"adGroup": f"{_C}/adGroups/-4", "asset": sitelink_name, "fieldType": "SITELINK"},
        {"adGroup": f"{_C}/adGroups/-4", "asset": callout_name, "fieldType": "CALLOUT"},
    ]
    data = GoogleAdsCreateCampaignOutput.model_validate(result).results[0].data
    assert ("asset", 2) in [(row.kind, row.created) for row in data.kinds]


async def test_a_rejected_request_records_nothing_created_and_gives_the_reason_once(
    monkeypatch,
) -> None:
    account = _Account(refuse_send=True)
    args = {"campaign": _campaign(), "ad_groups": [_ad_group()]}

    result, audit = await _run(monkeypatch, account, args)

    data = GoogleAdsCreateCampaignOutput.model_validate(result).results[0].data
    assert data.outcome == "failed" and data.campaign is None
    assert all(row.created == 0 for row in data.kinds)
    assert len(data.problems) == 1
    assert "A campaign with this name already exists." in data.problems[0].message
    assert audit.await_args.kwargs["status"] == AuditStatus.FAILURE


async def test_a_campaign_that_could_not_serve_is_refused_before_approval() -> None:
    args = {"campaign": _campaign(locations=[]), "ad_groups": [_ad_group(ads=[])]}
    request = GoogleAdsCreateCampaignRequest.model_validate(args)

    with pytest.raises(ModelRetry) as refused:
        tool_module._validate_args(
            _ctx(_entry()), request.campaign, request.ad_groups, status=request.status
        )

    assert "at least one location" in str(refused.value)
    assert "Waterproof Boots: needs at least one ad to serve." in str(refused.value)


async def test_a_click_bid_the_new_bidding_ignores_is_refused_after_approval_with_nothing_sent(
    monkeypatch,
) -> None:
    account = _Account()
    args = {"campaign": _campaign(), "ad_groups": [_ad_group(cpc_bid="0.90")]}

    result, _audit = await _run(monkeypatch, account, args)

    entry = GoogleAdsCreateCampaignOutput.model_validate(result).results[0]
    assert entry.status == "error"
    assert "the campaign uses Maximise Conversions" in entry.error_message
    assert account.mutates == []


async def test_a_change_of_account_since_approval_is_refused_with_nothing_sent(
    monkeypatch,
) -> None:
    account = _Account()
    other = replace(_entry(), external_id="222")
    args = {"campaign": _campaign(), "ad_groups": [_ad_group()]}

    result, _audit = await _run(monkeypatch, account, args, approved_entry=other)

    entry = GoogleAdsCreateCampaignOutput.model_validate(result).results[0]
    assert entry.status == "error" and "no longer selected" in entry.error_message
    assert account.mutates == []


async def test_approval_names_locations_and_reports_google_per_item_leaving_known_problems_out(
    monkeypatch,
) -> None:
    account = _Account(reject_location="1006886")
    args = {
        "campaign": _campaign(
            locations=[{"key": "2826"}, {"key": "1006886"}, {"key": "999999"}],
        ),
        "ad_groups": [_ad_group(), _ad_group(name="No Ads", ads=[])],
    }

    checks = (await _display(monkeypatch, account, args))["_checks"]

    assert checks["locations"] == _KNOWN_LOCATIONS
    assert checks["unknown_locations"] == ["999999"]
    sent = account.mutates[0]
    assert sent["validateOnly"] is True
    targeted = [
        operation["campaignCriterionOperation"]["create"]["location"]["geoTargetConstant"]
        for operation in sent["mutateOperations"]
        if "campaignCriterionOperation" in operation
    ]
    assert targeted == ["geoTargetConstants/2826", "geoTargetConstants/1006886"]
    assert [
        operation["adGroupOperation"]["create"]["name"]
        for operation in sent["mutateOperations"]
        if "adGroupOperation" in operation
    ] == ["Waterproof Boots"]
    assert checks["campaign_problems"] == [
        {
            "kind": "location",
            "key": "1006886",
            "message": "Google says: This location can't be targeted.",
        }
    ]
    assert checks["problems"] == [] and checks["request_problems"] == []


def _image(asset_id: str, field_type: str, customer_id: str = "111") -> dict[str, Any]:
    return {
        "asset": {
            "customer_id": customer_id,
            "asset_id": asset_id,
            "asset_type": "IMAGE",
            "label": f"Image {asset_id}",
        },
        "field_type": field_type,
    }


def _asset_group(**over: Any) -> dict[str, Any]:
    return {
        "name": "Rain Jackets",
        "final_url": "https://shop.test/rain-jackets",
        "headlines": ["Rain Jackets", "Stay Dry Outside", "Free Returns"],
        "long_headlines": ["Waterproof jackets for every trail"],
        "descriptions": ["Light, packable, and fully taped.", "Free UK delivery."],
        "images": [_image("301", "MARKETING_IMAGE"), _image("302", "SQUARE_MARKETING_IMAGE")],
        "search_themes": ["waterproof jacket"],
        **over,
    }


def _pmax(**over: Any) -> dict[str, Any]:
    return {
        "type": "performance_max",
        "name": "PMax Hiking UK",
        "budget": {"kind": "new", "daily_amount": "80"},
        "bidding": {"strategy": "MAXIMIZE_CONVERSION_VALUE", "target_roas": 4},
        "locations": [{"key": "2826", "name": "United Kingdom"}],
        "languages": [{"key": "1000", "name": "English"}],
        "business_name": "Northwind Outdoor",
        "logos": [_image("302", "LOGO")],
        **over,
    }


async def _run_pmax(monkeypatch, account: _Account, args: dict[str, Any]):
    entry = _entry()
    monkeypatch.setattr(tool_module, "google_ads_client", AsyncMock(return_value=account))
    monkeypatch.setattr(
        tool_module, "approved_display_args", lambda _ctx: {"_accounts": approval_accounts([entry])}
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        AsyncMock(return_value=uuid4()),
    )
    request = GoogleAdsCreateCampaignRequest.model_validate(args)
    result = await tool_module.google_ads_create_campaign(
        _ctx(entry), request.campaign, asset_groups=request.asset_groups, status=request.status
    )
    return GoogleAdsCreateCampaignOutput.model_validate(result).results[0]


async def test_performance_max_builds_brand_on_the_campaign_and_complete_asset_groups_atomically(
    monkeypatch,
) -> None:
    account = _Account()
    args = {
        "campaign": _pmax(
            final_url_expansion=False,
            conversion_goals=[{"category": "PURCHASE", "origin": "WEBSITE"}],
        ),
        "asset_groups": [_asset_group(headlines=["Rain Jackets", "Northwind Outdoor", "Dry"])],
    }

    entry = await _run_pmax(monkeypatch, account, args)

    sent = account.mutates[-1]
    assert sent["validateOnly"] is False and sent["partialFailure"] is False
    operations = sent["mutateOperations"]
    created = [(next(iter(op)), op[next(iter(op))]) for op in operations]
    campaign, group = f"{_C}/campaigns/-2", f"{_C}/assetGroups/-4"
    body = created[7][1]["create"]
    assert body["advertisingChannelType"] == "PERFORMANCE_MAX"
    assert body["brandGuidelinesEnabled"] is True
    assert body["maximizeConversionValue"] == {"targetRoas": 4}
    assert body["assetAutomationSettings"] == [
        {
            "assetAutomationType": "FINAL_URL_EXPANSION_TEXT_ASSET_AUTOMATION",
            "assetAutomationStatus": "OPTED_OUT",
        }
    ]
    # Text assets come before the campaign, one per distinct text, the business name included.
    assert [
        op["create"]["textAsset"]["text"] for kind, op in created if kind == "assetOperation"
    ] == [
        "Northwind Outdoor",
        "Rain Jackets",
        "Dry",
        "Waterproof jackets for every trail",
        "Light, packable, and fully taped.",
        "Free UK delivery.",
    ]
    assert [op["create"] for kind, op in created if kind == "campaignCriterionOperation"] == [
        {"campaign": campaign, "location": {"geoTargetConstant": "geoTargetConstants/2826"}},
        {"campaign": campaign, "language": {"languageConstant": "languageConstants/1000"}},
    ]
    assert [
        op["create"]["fieldType"] for kind, op in created if kind == "campaignAssetOperation"
    ] == [
        "BUSINESS_NAME",
        "LOGO",
    ]
    assert created[10] == (
        "assetGroupOperation",
        {
            "create": {
                "name": "Rain Jackets",
                "campaign": campaign,
                "finalUrls": ["https://shop.test/rain-jackets"],
                "status": "PAUSED",
                "resourceName": group,
            }
        },
    )
    links = [op["create"] for kind, op in created if kind == "assetGroupAssetOperation"]
    assert [link["fieldType"] for link in links] == [
        "HEADLINE",
        "HEADLINE",
        "HEADLINE",
        "LONG_HEADLINE",
        "DESCRIPTION",
        "DESCRIPTION",
        "MARKETING_IMAGE",
        "SQUARE_MARKETING_IMAGE",
    ]
    # The headline that repeats the business name links the same asset.
    assert links[1]["asset"] == f"{_C}/assets/-3"
    assert links[6]["asset"] == f"{_C}/assets/301"
    signals = [op["create"] for kind, op in created if kind == "assetGroupSignalOperation"]
    assert signals == [{"assetGroup": group, "searchTheme": {"text": "waterproof jacket"}}]
    # Google makes the campaign's goals with it, so each is updated last, in the same request.
    assert [op for kind, op in created if kind == "campaignConversionGoalOperation"] == [
        {
            "update": {
                "resourceName": f"{_C}/campaignConversionGoals/-2~PURCHASE~WEBSITE",
                "biddable": True,
            },
            "updateMask": "biddable",
        },
        {
            "update": {
                "resourceName": f"{_C}/campaignConversionGoals/-2~SIGNUP~WEBSITE",
                "biddable": False,
            },
            "updateMask": "biddable",
        },
    ]
    assert not any(
        kind == "campaignBudgetOperation" and op["create"]["explicitlyShared"]
        for kind, op in created
    )
    assert entry.data.outcome == "created" and entry.data.campaign_type == "performance_max"
    assert entry.data.asset_groups[0].reference.asset_group_id == "950"
    assert entry.data.asset_groups[0].reference.campaign_id == "800"


async def test_a_retail_campaign_shows_the_linked_feed_and_its_bare_asset_group_every_product(
    monkeypatch,
) -> None:
    account = _Account(merchant_ids=("5551234",))
    bare = {"name": "All Products", "final_url": "https://shop.test/"}
    args = {
        "campaign": _pmax(
            business_name=None, logos=[], merchant={"merchant_id": "5551234", "feed_label": "UK"}
        ),
        "asset_groups": [bare],
    }

    entry = await _run_pmax(monkeypatch, account, args)

    created = [next(iter(op)) for op in account.mutates[-1]["mutateOperations"]]
    operations = account.mutates[-1]["mutateOperations"]
    campaign = next(
        op["campaignOperation"]["create"] for op in operations if "campaignOperation" in op
    )
    assert campaign["shoppingSetting"] == {"merchantId": "5551234", "feedLabel": "UK"}
    assert "assetOperation" not in created and "campaignAssetOperation" not in created
    assert next(
        op["assetGroupListingGroupFilterOperation"]["create"]
        for op in operations
        if "assetGroupListingGroupFilterOperation" in op
    ) == {
        "assetGroup": f"{_C}/assetGroups/-3",
        "type": "UNIT_INCLUDED",
        "listingSource": "SHOPPING",
    }
    assert entry.data.outcome == "created"


async def test_a_merchant_center_account_not_linked_is_refused_after_approval_with_nothing_sent(
    monkeypatch,
) -> None:
    account = _Account(merchant_ids=("999",))
    args = {
        "campaign": _pmax(merchant={"merchant_id": "5551234"}),
        "asset_groups": [_asset_group()],
    }

    entry = await _run_pmax(monkeypatch, account, args)

    assert entry.status == "error" and "isn't linked" in entry.error_message
    assert account.mutates == []


async def test_an_asset_group_below_a_minimum_or_with_another_accounts_image_is_refused() -> None:
    args = {
        "campaign": _pmax(),
        "asset_groups": [
            _asset_group(
                headlines=["Rain Jackets", "Stay Dry Outside"],
                images=[
                    _image("301", "MARKETING_IMAGE", customer_id="222"),
                    _image("302", "SQUARE_MARKETING_IMAGE"),
                ],
            )
        ],
    }
    request = GoogleAdsCreateCampaignRequest.model_validate(args)

    with pytest.raises(ModelRetry) as refused:
        tool_module._validate_args(
            _ctx(_entry()), request.campaign, asset_groups=request.asset_groups
        )

    assert "Rain Jackets: needs at least 3 headlines, has 2." in str(refused.value)
    assert "Choose images and videos from the account the campaign goes in." in str(refused.value)


async def test_performance_max_approval_reads_images_feed_and_goals_and_dry_runs(
    monkeypatch,
) -> None:
    account = _Account()
    args = {
        "campaign": _pmax(),
        "asset_groups": [
            _asset_group(),
            # The landscape image doesn't fit the square shape, so Google isn't asked about it.
            _asset_group(
                name="Boots",
                images=[_image("301", "SQUARE_MARKETING_IMAGE"), _image("302", "MARKETING_IMAGE")],
            ),
        ],
    }

    checks = (await _display(monkeypatch, account, args))["_checks"]

    assert checks["images"]["302"]["fits"] == ["SQUARE_MARKETING_IMAGE", "LOGO"]
    assert checks["unknown_images"] == [] and checks["languages"] == {"1000": "English"}
    assert [goal["name"] for goal in checks["account_goals"]] == [
        "Purchase from website",
        "Signup from website",
    ]
    sent = account.mutates[0]
    # Google refuses partial failure for Performance Max asset groups, even in a dry run.
    assert sent["validateOnly"] is True and sent["partialFailure"] is False
    assert [
        op["assetGroupOperation"]["create"]["name"]
        for op in sent["mutateOperations"]
        if "assetGroupOperation" in op
    ] == ["Rain Jackets"]
