# apps/api/tests/integrations/google_ads/test_update_status_tool.py

"""Turning Google Ads objects on or off: checks before approval, one request after, and read-back."""

import re
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry

from integrations.google_ads.references import (
    GoogleAdsAdGroupReference,
    GoogleAdsAdReference,
    GoogleAdsAssetGroupReference,
    GoogleAdsCampaignReference,
    GoogleAdsKeywordReference,
)
from integrations.google_ads.tools import update_status as tool_module
from integrations.google_ads.tools.schemas.status import GoogleAdsUpdateStatusOutput
from services.audit_events import AuditStatus
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.google_ads.support import _writable_google_ads_entry

_C = "customers/111"
_CAMPAIGN = f"{_C}/campaigns/10"
_AD_GROUP = f"{_C}/adGroups/20"
_AD = f"{_C}/adGroupAds/20~30"
_KEYWORD = f"{_C}/adGroupCriteria/20~40"
_ASSET_GROUP = f"{_C}/assetGroups/50"
_ROW_KEYS = {
    "campaigns": "campaign",
    "adGroups": "adGroup",
    "adGroupAds": "adGroupAd",
    "adGroupCriteria": "adGroupCriterion",
    "assetGroups": "assetGroup",
}


class _Account:
    """One Google Ads account: answers status reads and applies `googleAds:mutate` requests."""

    def __init__(self, statuses: dict[str, str], *, rejected: dict[str, str] | None = None):
        self.statuses = statuses
        self.rejected = rejected or {}
        self.mutates: list[dict[str, Any]] = []

    async def post(self, path: str, **kwargs: Any) -> Any:
        body = kwargs["json"]
        if path.endswith("googleAds:searchStream"):
            names = re.findall(r"'([^']+)'", body["query"])
            return [{"results": [self._row(name) for name in names if name in self.statuses]}]
        self.mutates.append(body)
        responses, errors = [], []
        for index, operation in enumerate(body["mutateOperations"]):
            ((key, value),) = operation.items()
            name = value["update"]["resourceName"]
            if name in self.rejected:
                responses.append({})
                errors.append(_error(index, self.rejected[name]))
                continue
            if not body["validateOnly"]:
                self.statuses[name] = value["update"]["status"]
            responses.append({key.replace("Operation", "Result"): {"resourceName": name}})
        reply: dict[str, Any] = {"mutateOperationResponses": responses}
        if errors:
            reply["partialFailureError"] = {"details": [{"errors": errors}]}
        return reply

    def _row(self, name: str) -> dict[str, Any]:
        item: dict[str, Any] = {"resourceName": name, "status": self.statuses[name]}
        if name == _KEYWORD:
            item.update(type="KEYWORD", negative=False, keyword={"text": "trail shoes"})
        if name == _AD:
            item["ad"] = {"id": "30", "name": "Grip Any Trail"}
        campaign = {"id": "10", "name": "Trail", "status": self.statuses[_CAMPAIGN]}
        row = {"campaign": campaign, _ROW_KEYS[name.split("/")[2]]: item}
        if name == _CAMPAIGN:
            row["campaign"] = {**campaign, **item}
        if name in {_AD, _KEYWORD}:
            row["adGroup"] = {"id": "20", "name": "Shoes", "status": self.statuses[_AD_GROUP]}
        return row


def _error(index: int, message: str) -> dict[str, Any]:
    return {
        "message": message,
        "errorCode": {"adGroupError": "INVALID"},
        "location": {"fieldPathElements": [{"fieldName": "mutate_operations", "index": index}]},
    }


def _changes(**statuses: str) -> list[Any]:
    references = {
        "campaign": GoogleAdsCampaignReference(customer_id="111", campaign_id="10", label="Trail"),
        "ad_group": GoogleAdsAdGroupReference(
            customer_id="111", campaign_id="10", ad_group_id="20", label="Shoes"
        ),
        "ad": GoogleAdsAdReference(
            customer_id="111", campaign_id="10", ad_group_id="20", ad_id="30", label="Ad"
        ),
        "keyword": GoogleAdsKeywordReference(
            customer_id="111",
            campaign_id="10",
            ad_group_id="20",
            criterion_id="40",
            text="trail shoes",
            match_type="PHRASE",
            status="ENABLED",
            label="trail shoes",
        ),
        "asset_group": GoogleAdsAssetGroupReference(
            customer_id="111", campaign_id="10", asset_group_id="50", label="Spring"
        ),
    }
    return tool_module.GoogleAdsUpdateStatusRequest.model_validate(
        {
            "changes": [
                {"kind": kind, kind: references[kind], "status": status}
                for kind, status in statuses.items()
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


async def _run(
    monkeypatch, account: _Account, changes: list[Any], display: dict[str, Any], *, proposed=None
):
    monkeypatch.setattr(tool_module, "google_ads_client", AsyncMock(return_value=account))
    monkeypatch.setattr(tool_module, "approved_display_args", lambda _ctx: display)
    monkeypatch.setattr(
        tool_module,
        "proposed_args",
        lambda _ctx: (
            proposed or {"changes": [change.model_dump(mode="json") for change in changes]}
        ),
    )
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
        tool_name="google_ads_update_status",
        tool_call_id="update-status-call",
    )
    return await tool_module.google_ads_update_status(ctx, changes), audit


async def test_one_request_turns_off_every_kind_and_reports_an_equal_status_as_already_set(
    monkeypatch,
) -> None:
    account = _Account(
        {
            _CAMPAIGN: "ENABLED",
            _AD_GROUP: "ENABLED",
            _AD: "ENABLED",
            _KEYWORD: "ENABLED",
            _ASSET_GROUP: "PAUSED",
        }
    )
    changes = _changes(
        campaign="PAUSED", ad_group="PAUSED", ad="PAUSED", keyword="PAUSED", asset_group="PAUSED"
    )
    display = await _display(monkeypatch, account, changes)

    result, audit = await _run(monkeypatch, account, changes, display)

    sent = account.mutates[-1]
    assert sent["validateOnly"] is False and sent["partialFailure"] is True
    assert sent["mutateOperations"] == [
        {
            f"{resource}Operation": {
                "update": {"resourceName": name, "status": "PAUSED"},
                "updateMask": "status",
            }
        }
        for resource, name in (
            ("campaign", _CAMPAIGN),
            ("adGroup", _AD_GROUP),
            ("adGroupAd", _AD),
            ("adGroupCriterion", _KEYWORD),
        )
    ]
    shown = GoogleAdsUpdateStatusOutput.model_validate(result.metadata["public_result"])
    rows = shown.results[0].data.objects
    assert [(row.name, row.before, row.after, row.outcome) for row in rows] == [
        ("Trail", "ENABLED", "PAUSED", "updated"),
        ("Shoes", "ENABLED", "PAUSED", "updated"),
        ("Grip Any Trail", "ENABLED", "PAUSED", "updated"),
        ("trail shoes", "ENABLED", "PAUSED", "updated"),
        ("Spring", "PAUSED", "PAUSED", "already_set"),
    ]
    # The agent gets the counts and only what didn't change, so a 500 row result stays small.
    told = result.return_value["results"][0]["data"]
    assert told["counts"] == {"updated": 4, "already_set": 1, "failed": 0, "unverified": 0}
    assert told["objects"] == []
    assert audit.await_args.kwargs["status"] == AuditStatus.SUCCESS


async def test_approval_shows_googles_rejection_and_whether_the_parent_is_off(monkeypatch) -> None:
    account = _Account(
        {_CAMPAIGN: "PAUSED", _AD_GROUP: "PAUSED", _AD: "REMOVED", _KEYWORD: "PAUSED"},
        rejected={_AD_GROUP: "Ad group can't be enabled"},
    )
    changes = _changes(ad_group="ENABLED", ad="ENABLED", keyword="ENABLED", asset_group="ENABLED")

    checks = (await _display(monkeypatch, account, changes))["_checks"]

    assert account.mutates and all(body["validateOnly"] for body in account.mutates)
    assert {name: check["problem"] for name, check in checks.items()} == {
        _AD_GROUP: "Google says: Ad group can't be enabled",
        _AD: "Removed items can't be turned on or off.",
        _KEYWORD: None,
        _ASSET_GROUP: "This no longer exists in Google Ads.",
    }
    keyword = checks[_KEYWORD]
    assert (keyword["campaign_status"], keyword["ad_group_status"]) == ("PAUSED", "PAUSED")


async def test_an_object_added_on_the_card_after_approval_is_refused(monkeypatch) -> None:
    account = _Account({_CAMPAIGN: "ENABLED", _AD_GROUP: "ENABLED"})
    proposed = {"changes": [_changes(campaign="PAUSED")[0].model_dump(mode="json")]}
    changes = _changes(campaign="PAUSED", ad_group="PAUSED")
    display = await _display(monkeypatch, account, changes)

    with pytest.raises(ModelRetry, match="added after approval"):
        await _run(monkeypatch, account, changes, display, proposed=proposed)

    assert all(body["validateOnly"] for body in account.mutates)


async def test_a_reference_to_an_account_outside_the_context_is_refused(monkeypatch) -> None:
    account = _Account({_CAMPAIGN: "ENABLED"})
    foreign = GoogleAdsCampaignReference(customer_id="222", campaign_id="10", label="Other")
    changes = tool_module.GoogleAdsUpdateStatusRequest.model_validate(
        {"changes": [{"kind": "campaign", "campaign": foreign, "status": "PAUSED"}]}
    ).changes

    with pytest.raises(ModelRetry, match="no longer in the active integration context"):
        await _run(monkeypatch, account, changes, {"_checks": {}})

    assert account.mutates == []
