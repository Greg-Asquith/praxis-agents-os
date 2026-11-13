# apps/api/tests/integrations/google_ads/test_create_asset_groups_tool.py

"""Adding asset groups to a live Performance Max campaign: the campaign rules, signals, dry run."""

from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from integrations.google_ads.references import GoogleAdsCampaignReference
from integrations.google_ads.tools import create_asset_groups as tool_module
from integrations.google_ads.tools.schemas.performance_max import (
    GoogleAdsCreateAssetGroupsOutput,
    GoogleAdsCreateAssetGroupsRequest,
)
from services.audit_events import AuditStatus
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.google_ads.support import _writable_google_ads_entry

_C = "customers/111"
_IMAGES = {
    "301": {"widthPixels": 1200, "heightPixels": 628},
    "302": {"widthPixels": 1200, "heightPixels": 1200},
}


class _Account:
    """One account's Performance Max campaign: answers its reads and applies mutates."""

    def __init__(
        self,
        *,
        channel: str = "PERFORMANCE_MAX",
        brand_guidelines: bool = True,
        merchant_id: str | None = None,
        names: tuple[str, ...] = ("Existing",),
    ):
        self.channel = channel
        self.brand_guidelines = brand_guidelines
        self.merchant_id = merchant_id
        self.names = names
        self.mutates: list[dict[str, Any]] = []

    async def post(self, _path: str, **kwargs: Any) -> Any:
        body = kwargs["json"]
        if "query" in body:
            return [{"results": self._rows(body["query"])}]
        self.mutates.append(body)
        responses = []
        for index, operation in enumerate(body["mutateOperations"]):
            resource = next(iter(operation)).removesuffix("Operation")
            name = {
                "asset": f"assets/{500 + index}",
                "assetGroup": "assetGroups/950",
                "assetGroupAsset": f"assetGroupAssets/950~{500 + index}~HEADLINE",
                "assetGroupSignal": f"assetGroupSignals/950~{index}",
                "assetGroupListingGroupFilter": f"assetGroupListingGroupFilters/950~{index}",
                "audience": "audiences/77",
            }[resource]
            responses.append({f"{resource}Result": {"resourceName": f"{_C}/{name}"}})
        return {"mutateOperationResponses": responses}

    def _rows(self, query: str) -> list[dict[str, Any]]:
        if "FROM campaign " in query:
            campaign: dict[str, Any] = {
                "id": "10",
                "name": "PMax Hiking UK",
                "advertisingChannelType": self.channel,
                "brandGuidelinesEnabled": self.brand_guidelines,
            }
            if self.merchant_id:
                campaign["shoppingSetting"] = {"merchantId": self.merchant_id}
            return [{"campaign": campaign}]
        if "FROM asset_group " in query:
            return [{"assetGroup": {"id": "1", "name": name}} for name in self.names]
        if "FROM asset " in query:
            return [
                {"asset": {"id": asset_id, "type": "IMAGE", "imageAsset": {"fullSize": size}}}
                for asset_id, size in _IMAGES.items()
                if asset_id in query
            ]
        if "FROM user_list " in query and "401" in query:
            return [{"userList": {"id": "401", "name": "Past Buyers"}}]
        return []


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


def _args(*groups: dict[str, Any]) -> dict[str, Any]:
    campaign = GoogleAdsCampaignReference(customer_id="111", campaign_id="10", label="PMax")
    return {"campaign": campaign.model_dump(mode="json"), "asset_groups": list(groups)}


def _entry():
    entry = _writable_google_ads_entry()
    metadata = {**entry.permissions_metadata, "currency_code": "GBP", "time_zone": "Europe/London"}
    return replace(entry, permissions_metadata=metadata)


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


async def _run(monkeypatch, account: _Account, args: dict[str, Any]):
    monkeypatch.setattr(tool_module, "google_ads_client", AsyncMock(return_value=account))
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(_entry(),)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name="google_ads_create_asset_groups",
        tool_call_id="create-asset-groups-call",
    )
    request = GoogleAdsCreateAssetGroupsRequest.model_validate(args)
    result = await tool_module.google_ads_create_asset_groups(
        ctx, request.campaign, request.asset_groups, request.status
    )
    return GoogleAdsCreateAssetGroupsOutput.model_validate(result).results[0], audit


async def test_one_atomic_request_adds_a_group_with_one_audience_signal_holding_every_segment(
    monkeypatch,
) -> None:
    account = _Account()
    signals = [
        {"kind": "user_list", "key": "401", "name": "Past Buyers"},
        {"kind": "user_interest", "key": "80432"},
        {"kind": "custom_audience", "key": "612"},
    ]
    url_options = {
        "final_url_suffix": "utm_source=google",
        "tracking_template": "",
        "custom_parameters": [{"key": "season", "value": "winter"}],
    }
    args = _args(_asset_group(audience_signals=signals, url_options=url_options))

    entry, audit = await _run(monkeypatch, account, args)

    sent = account.mutates[-1]
    assert sent["validateOnly"] is False and sent["partialFailure"] is False
    created = [(next(iter(op)), op[next(iter(op))]["create"]) for op in sent["mutateOperations"]]
    group = f"{_C}/assetGroups/-1"
    assert next(body for kind, body in created if kind == "assetGroupOperation") == {
        "name": "Rain Jackets",
        "campaign": f"{_C}/campaigns/10",
        "finalUrls": ["https://shop.test/rain-jackets"],
        "status": "PAUSED",
        # An empty tracking template is one the new group doesn't have.
        "finalUrlSuffix": "utm_source=google",
        "urlCustomParameters": [{"key": "season", "value": "winter"}],
        "resourceName": group,
    }
    # A campaign without a feed takes no listing filter.
    assert "assetGroupListingGroupFilterOperation" not in [kind for kind, _ in created]
    # The asset group's own audience comes before the signal that names it.
    audience_at = [kind for kind, _ in created].index("audienceOperation")
    assert created[audience_at][1] == {
        "scope": "ASSET_GROUP",
        "assetGroup": group,
        "dimensions": [
            {
                "audienceSegments": {
                    "segments": [
                        {"userList": {"userList": f"{_C}/userLists/401"}},
                        {"userInterest": {"userInterestCategory": f"{_C}/userInterests/80432"}},
                        {"customAudience": {"customAudience": f"{_C}/customAudiences/612"}},
                    ]
                }
            }
        ],
        "resourceName": f"{_C}/audiences/-8",
    }
    assert [body for kind, body in created[audience_at:] if kind == "assetGroupSignalOperation"][
        -1
    ] == {"assetGroup": group, "audience": {"audience": f"{_C}/audiences/-8"}}
    assert entry.data.asset_groups[0].reference.asset_group_id == "950"
    assert entry.data.asset_groups[0].reference.campaign_id == "10"
    assert entry.data.asset_groups[0].audience_signals == 3
    assert ("audience_signal", 1) in [(row.kind, row.created) for row in entry.data.kinds]
    assert audit.await_args.kwargs["status"] == AuditStatus.SUCCESS


@pytest.mark.parametrize(
    ("account", "reason"),
    [
        (_Account(channel="SEARCH"), "only go in Performance Max campaigns"),
        (_Account(brand_guidelines=False), "Turn on brand guidelines"),
        (_Account(names=("rain jackets",)), "already has an asset group by this name"),
    ],
)
async def test_a_campaign_that_cant_take_the_groups_is_refused_after_approval_with_nothing_sent(
    monkeypatch, account: _Account, reason: str
) -> None:
    entry, _audit = await _run(monkeypatch, account, _args(_asset_group()))

    assert entry.status == "error" and reason in entry.error_message
    assert account.mutates == []


async def test_approval_names_audiences_and_keeps_groups_the_card_faults_out_of_the_dry_run(
    monkeypatch,
) -> None:
    account = _Account(merchant_id="5551234")
    args = _args(
        # A retail campaign fills a group with no assets of its own from the feed.
        {"name": "All Products", "final_url": "https://shop.test/"},
        _asset_group(
            name="Boots", audience_signals=[{"kind": "user_list", "key": "999", "name": "Gone"}]
        ),
        _asset_group(audience_signals=[{"kind": "user_list", "key": "401"}]),
    )

    checks = (await _display(monkeypatch, account, args))["_checks"]

    assert checks["campaign"]["retail"] is True and checks["campaign"]["problem"] is None
    assert checks["audiences"] == {"user_list:401": "Past Buyers"}
    assert checks["unknown_audiences"] == ["user_list:999"]
    assert checks["existing_names"] == ["Existing"]
    sent = account.mutates[0]
    assert sent["validateOnly"] is True and sent["partialFailure"] is False
    assert [
        op["assetGroupOperation"]["create"]["name"]
        for op in sent["mutateOperations"]
        if "assetGroupOperation" in op
    ] == ["All Products", "Rain Jackets"]
