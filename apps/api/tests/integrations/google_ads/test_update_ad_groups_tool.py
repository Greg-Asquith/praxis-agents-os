# apps/api/tests/integrations/google_ads/test_update_ad_groups_tool.py

"""Changing ad group settings: strategy checks before approval, one masked request, read-back."""

import re
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

from integrations.google_ads.references import GoogleAdsAdGroupReference
from integrations.google_ads.tools import update_ad_groups as tool_module
from integrations.google_ads.tools.schemas.ad_group_updates import GoogleAdsUpdateAdGroupsOutput
from integrations.google_ads.tools.utils import edit_runs
from services.audit_events import AuditStatus
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.google_ads.support import _writable_google_ads_entry

_MANUAL = {"name": "Manual Campaign", "status": "ENABLED", "biddingStrategyType": "MANUAL_CPC"}
_TARGET_CPA = {
    "name": "Conversions Campaign",
    "status": "ENABLED",
    "biddingStrategyType": "MAXIMIZE_CONVERSIONS",
    "maximizeConversions": {"targetCpaMicros": "15000000"},
}
_VALUE = {
    "name": "Value Campaign",
    "status": "ENABLED",
    "biddingStrategyType": "MAXIMIZE_CONVERSION_VALUE",
    "maximizeConversionValue": {},
}


def _name(ad_group_id: str) -> str:
    return f"customers/111/adGroups/{ad_group_id}"


def _ad_group(ad_group_id: str, campaign: dict[str, Any], **values: Any) -> dict[str, Any]:
    return {
        "adGroup": {
            "resourceName": _name(ad_group_id),
            "id": ad_group_id,
            "name": f"Ad Group {ad_group_id}",
            "status": "ENABLED",
            "cpcBidMicros": "500000",
            "adRotationMode": "OPTIMIZE",
            **values,
        },
        "campaign": dict(campaign),
    }


class _Account:
    """One Google Ads account: answers ad group reads and applies `googleAds:mutate` requests."""

    def __init__(self, *rows: dict[str, Any]):
        self.rows = {row["adGroup"]["resourceName"]: row for row in rows}
        self.mutates: list[dict[str, Any]] = []

    async def post(self, path: str, **kwargs: Any) -> Any:
        body = kwargs["json"]
        if path.endswith("googleAds:searchStream"):
            ids = re.search(r"IN \(([^)]*)\)", body["query"]).group(1).split(", ")
            rows = [row for row in self.rows.values() if row["adGroup"]["id"] in ids]
            return [{"results": rows}]
        self.mutates.append(body)
        responses = []
        for operation in body["mutateOperations"]:
            update = operation["adGroupOperation"]["update"]
            name = update["resourceName"]
            if not body["validateOnly"]:
                live = self.rows[name]["adGroup"]
                for field in operation["adGroupOperation"]["updateMask"].split(","):
                    if field in update:
                        live[field] = update[field]
                    else:
                        live.pop(field, None)
            responses.append({"adGroupResult": {"resourceName": name}})
        return {"mutateOperationResponses": responses}


def _changes(*entries: dict[str, Any]) -> list[Any]:
    return tool_module.GoogleAdsUpdateAdGroupsRequest.model_validate(
        {
            "changes": [
                {
                    **entry,
                    "ad_group": GoogleAdsAdGroupReference(
                        customer_id="111",
                        campaign_id="10",
                        ad_group_id=entry["ad_group"],
                        label="Ad Group",
                    ),
                }
                for entry in entries
            ]
        }
    ).changes


def _entry():
    entry = _writable_google_ads_entry()
    metadata = {**entry.permissions_metadata, "currency_code": "GBP", "time_zone": "Europe/London"}
    return replace(entry, permissions_metadata=metadata)


async def _display(monkeypatch, account: _Account, changes: list[Any]) -> dict[str, Any]:
    monkeypatch.setattr(
        tool_module, "google_ads_client_for_principal", AsyncMock(return_value=account)
    )
    deps = SimpleNamespace(
        db=None,
        user=None,
        workspace=None,
        active_context=ResolvedActiveContext(entries=(_entry(),)),
    )
    args = {"changes": [change.model_dump(mode="json") for change in changes]}
    return await tool_module._approval_display_args(deps, args)


async def _run(monkeypatch, account: _Account, changes: list[Any], display: dict[str, Any]):
    monkeypatch.setattr(edit_runs, "google_ads_client", AsyncMock(return_value=account))
    monkeypatch.setattr(tool_module, "approved_display_args", lambda _ctx: display)
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
        tool_name="google_ads_update_ad_groups",
        tool_call_id="update-ad-groups-call",
    )
    result = await tool_module.google_ads_update_ad_groups(ctx, changes)
    return GoogleAdsUpdateAdGroupsOutput.model_validate(result).results[0].data, audit


async def test_one_request_masks_only_the_changed_settings_and_clears_a_target(
    monkeypatch,
) -> None:
    account = _Account(
        _ad_group("1", _MANUAL),
        _ad_group("2", _TARGET_CPA, targetCpaMicros="12000000"),
    )
    changes = _changes(
        {
            "ad_group": "1",
            "name": "Trail  Shoes",
            "cpc_bid": "0.80",
            "url_options": {"final_url_suffix": "src=ads"},
            "ad_rotation": "OPTIMIZE",
        },
        {"ad_group": "2", "target_cpa": "none"},
    )
    display = await _display(monkeypatch, account, changes)

    data, audit = await _run(monkeypatch, account, changes, display)

    assert account.mutates[-1]["mutateOperations"] == [
        {
            "adGroupOperation": {
                "update": {
                    "resourceName": _name("1"),
                    "name": "Trail Shoes",
                    "cpcBidMicros": "800000",
                    "finalUrlSuffix": "src=ads",
                },
                # Ad rotation is already Optimise, so it stays out of the mask.
                "updateMask": "name,cpcBidMicros,finalUrlSuffix",
            }
        },
        # The target is in the mask and not the body, which removes the override.
        {
            "adGroupOperation": {
                "update": {"resourceName": _name("2")},
                "updateMask": "targetCpaMicros",
            }
        },
    ]
    manual, smart = data.ad_groups
    assert [(row.setting, row.before, row.after, row.outcome) for row in manual.settings] == [
        ("name", "Ad Group 1", "Trail Shoes", "updated"),
        ("cpc_bid", "0.5", "0.8", "updated"),
        ("final_url_suffix", None, "src=ads", "updated"),
        ("ad_rotation", "OPTIMIZE", "OPTIMIZE", "already_set"),
    ]
    assert [(row.before, row.after) for row in smart.settings] == [("12", None)]
    assert audit.await_args.kwargs["status"] == AuditStatus.SUCCESS


async def test_bids_the_campaign_strategy_does_not_use_are_refused_before_any_request(
    monkeypatch,
) -> None:
    account = _Account(_ad_group("1", _TARGET_CPA), _ad_group("2", _VALUE))
    changes = _changes({"ad_group": "1", "cpc_bid": "1.10"}, {"ad_group": "2", "target_roas": 4})

    display = await _display(monkeypatch, account, changes)
    data, _audit = await _run(monkeypatch, account, changes, display)

    checks = display["_checks"]
    assert set(checks[_name("1")]["problems"]) == {"cpc_bid"}
    assert set(checks[_name("2")]["problems"]) == {"target_roas"}
    assert account.mutates == []
    assert {group.settings[0].outcome for group in data.ad_groups} == {"failed"}


async def test_a_bid_is_refused_when_the_campaign_strategy_changed_since_approval(
    monkeypatch,
) -> None:
    account = _Account(_ad_group("1", _MANUAL))
    changes = _changes({"ad_group": "1", "cpc_bid": "0.90"})
    display = await _display(monkeypatch, account, changes)
    # Someone moves the campaign to Maximise Conversions, so Google stops using the bid.
    account.rows[_name("1")]["campaign"] = dict(_TARGET_CPA)

    data, _audit = await _run(monkeypatch, account, changes, display)

    assert [body["validateOnly"] for body in account.mutates] == [True]
    assert data.ad_groups[0].error_code == "CHANGED_SINCE_APPROVAL"
    assert account.rows[_name("1")]["adGroup"]["cpcBidMicros"] == "500000"


async def test_a_change_the_approval_check_did_not_cover_is_refused(monkeypatch) -> None:
    account = _Account(_ad_group("1", _MANUAL))
    display = await _display(monkeypatch, account, _changes({"ad_group": "1", "name": "Trail"}))
    edited = _changes({"ad_group": "1", "name": "Trail", "cpc_bid": "5"})

    data, _audit = await _run(monkeypatch, account, edited, display)

    assert [body["validateOnly"] for body in account.mutates] == [True]
    assert data.ad_groups[0].message == tool_module.NOT_SHOWN
    assert account.rows[_name("1")]["adGroup"]["name"] == "Ad Group 1"
