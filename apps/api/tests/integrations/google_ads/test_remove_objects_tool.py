# apps/api/tests/integrations/google_ads/test_remove_objects_tool.py

"""Removing Google Ads items: what each takes with it, budgets still in use, and send order."""

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
    GoogleAdsCampaignBudgetReference,
    GoogleAdsKeywordReference,
)
from integrations.google_ads.tools import remove_objects as tool_module
from integrations.google_ads.tools.schemas.removals import GoogleAdsRemoveObjectsOutput
from services.audit_events import AuditStatus
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.google_ads.support import _writable_google_ads_entry

_C = "customers/111"
_CAMPAIGN = f"{_C}/campaigns/10"
_AD_GROUP = f"{_C}/adGroups/20"
_OTHER_AD_GROUP = f"{_C}/adGroups/21"
_KEYWORD = f"{_C}/adGroupCriteria/21~40"
_UNUSED_BUDGET = f"{_C}/campaignBudgets/7"
_USED_BUDGET = f"{_C}/campaignBudgets/8"
# Each GAQL resource's row key in Google's replies.
_ROW_KEYS = {
    "campaign": "campaign",
    "ad_group": "adGroup",
    "ad_group_ad": "adGroupAd",
    "ad_group_criterion": "adGroupCriterion",
    "campaign_budget": "campaignBudget",
}


class _Account:
    """One account's objects by resource name; answers reads and applies `googleAds:mutate`."""

    def __init__(self, *, rejected: dict[str, str] | None = None) -> None:
        campaign = {"resource": "campaign", "name": "Trail Running Shoes", "budget": _USED_BUDGET}
        self.objects: dict[str, dict[str, Any]] = {
            _CAMPAIGN: campaign,
            _AD_GROUP: {"resource": "ad_group", "name": "Summer Sandals"},
            _OTHER_AD_GROUP: {"resource": "ad_group", "name": "Hiking Boots"},
            f"{_C}/adGroupAds/20~30": {"resource": "ad_group_ad", "parent": _AD_GROUP},
            f"{_C}/adGroupCriteria/20~41": {"resource": "ad_group_criterion", "parent": _AD_GROUP},
            f"{_C}/adGroupCriteria/20~42": {"resource": "ad_group_criterion", "parent": _AD_GROUP},
            _KEYWORD: {
                "resource": "ad_group_criterion",
                "parent": _OTHER_AD_GROUP,
                "name": "walking sandals sale",
            },
            _UNUSED_BUDGET: {"resource": "campaign_budget", "name": "Spring Promo Shared"},
            _USED_BUDGET: {"resource": "campaign_budget", "name": "Brand Shared"},
        }
        for item in self.objects.values():
            item["status"] = "ENABLED"
        # Google rejects these when they are sent, but not in the dry run.
        self.rejected = rejected or {}
        self.mutates: list[dict[str, Any]] = []

    def _row(self, name: str) -> dict[str, Any]:
        item = self.objects[name]
        body: dict[str, Any] = {
            "resourceName": name,
            "name": item.get("name"),
            "status": item["status"],
        }
        if item["resource"] == "ad_group_criterion":
            body.update(type="KEYWORD", negative=False, keyword={"text": item.get("name")})
        row = {
            _ROW_KEYS[item["resource"]]: body,
            "campaign": {"id": "10", "name": "Trail Running Shoes", "status": "ENABLED"},
        }
        if "parent" in item:
            row["adGroup"] = {"id": item["parent"].rsplit("/", 1)[-1], "name": "Hiking Boots"}
        return row

    def _search(self, query: str) -> list[dict[str, Any]]:
        resource = re.search(r"FROM (\w+)", query).group(1)
        field = re.search(r"(\w+\.\w+) IN \(", query).group(1)
        names = re.findall(r"'(customers/[^']+)'", query)
        live = {
            name: item
            for name, item in self.objects.items()
            if item["status"] != "REMOVED" and item["resource"] == resource
        }
        if field == f"{resource}.resource_name":
            return [self._row(name) for name in names if name in self.objects]
        if field == "ad_group.resource_name":
            return [
                {"adGroup": {"resourceName": item["parent"]}}
                for item in live.values()
                if item.get("parent") in names
            ]
        return [
            {"campaign": {"name": item["name"], "campaignBudget": item["budget"]}}
            for item in live.values()
            if item.get("budget") in names
        ]

    async def post(self, path: str, **kwargs: Any) -> Any:
        body = kwargs["json"]
        if path.endswith("googleAds:searchStream"):
            return [{"results": self._search(body["query"])}]
        self.mutates.append(body)
        responses, errors = [], []
        for index, operation in enumerate(body["mutateOperations"]):
            ((key, value),) = operation.items()
            name = value["remove"]
            if name in self.rejected and not body["validateOnly"]:
                responses.append({})
                errors.append(
                    {
                        "message": self.rejected[name],
                        "errorCode": {"criterionError": "CANNOT_REMOVE"},
                        "location": {
                            "fieldPathElements": [
                                {"fieldName": "mutate_operations", "index": index}
                            ]
                        },
                    }
                )
                continue
            if not body["validateOnly"]:
                self.objects[name]["status"] = "REMOVED"
            responses.append({key.replace("Operation", "Result"): {"resourceName": name}})
        reply: dict[str, Any] = {"mutateOperationResponses": responses}
        if errors:
            reply["partialFailureError"] = {"details": [{"errors": errors}]}
        return reply


def _items(*kinds: tuple[str, str]) -> list[Any]:
    references = {
        "ad_group": GoogleAdsAdGroupReference(
            customer_id="111", campaign_id="10", ad_group_id="20", label="Summer Sandals"
        ),
        "keyword": GoogleAdsKeywordReference(
            customer_id="111",
            campaign_id="10",
            ad_group_id="21",
            criterion_id="40",
            text="walking sandals sale",
            match_type="PHRASE",
            status="ENABLED",
            label="walking sandals sale",
        ),
        "unused_budget": GoogleAdsCampaignBudgetReference(
            customer_id="111", budget_id="7", label="Spring Promo Shared"
        ),
        "used_budget": GoogleAdsCampaignBudgetReference(
            customer_id="111", budget_id="8", label="Brand Shared"
        ),
    }
    return tool_module.GoogleAdsRemoveObjectsRequest.model_validate(
        {"items": [{"kind": kind, kind: references[name]} for kind, name in kinds]}
    ).items


def _entry():
    entry = _writable_google_ads_entry()
    metadata = {**entry.permissions_metadata, "currency_code": "GBP", "time_zone": "Europe/London"}
    return replace(entry, permissions_metadata=metadata)


async def _display(monkeypatch, account: _Account, items: list[Any]) -> dict[str, Any]:
    monkeypatch.setattr(
        tool_module, "google_ads_client_for_principal", AsyncMock(return_value=account)
    )
    deps = SimpleNamespace(
        db=None,
        user=None,
        workspace=None,
        active_context=ResolvedActiveContext(entries=(_entry(),)),
    )
    args = {"items": [item.model_dump(mode="json") for item in items]}
    return await tool_module._approval_display_args(deps, args)


async def _run(monkeypatch, account: _Account, items: list[Any], display, *, proposed=None):
    monkeypatch.setattr(tool_module, "google_ads_client", AsyncMock(return_value=account))
    monkeypatch.setattr(tool_module, "approved_display_args", lambda _ctx: display)
    monkeypatch.setattr(
        tool_module,
        "proposed_args",
        lambda _ctx: proposed or {"items": [item.model_dump(mode="json") for item in items]},
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
        tool_name="google_ads_remove_objects",
        tool_call_id="remove-objects-call",
    )
    result = await tool_module.google_ads_remove_objects(ctx, items)
    return GoogleAdsRemoveObjectsOutput.model_validate(result).results[0].data, audit


async def test_one_request_removes_children_first_and_records_each_outcome(monkeypatch) -> None:
    account = _Account(rejected={_KEYWORD: "The keyword can't be removed."})
    items = _items(("ad_group", "ad_group"), ("budget", "unused_budget"), ("keyword", "keyword"))
    display = await _display(monkeypatch, account, items)

    data, audit = await _run(monkeypatch, account, items, display)

    assert display["_checks"][_AD_GROUP]["dependants"] == {
        "ads": 1,
        "keywords": 2,
        "truncated": False,
    }
    sent = [body for body in account.mutates if not body["validateOnly"]]
    assert [(body["mutateOperations"], body["partialFailure"]) for body in sent] == [
        (
            [
                # The keyword goes before any ad group, so removing its parent can't fail it.
                {"adGroupCriterionOperation": {"remove": _KEYWORD}},
                {"adGroupOperation": {"remove": _AD_GROUP}},
                {"campaignBudgetOperation": {"remove": _UNUSED_BUDGET}},
            ],
            True,
        )
    ]
    assert [(row.name, row.outcome) for row in data.objects] == [
        ("Summer Sandals", "removed"),
        ("Spring Promo Shared", "removed"),
        ("walking sandals sale", "failed"),
    ]
    assert data.objects[2].message == "The keyword can't be removed."
    assert audit.await_args.kwargs["status"] == AuditStatus.PARTIAL


async def test_a_budget_a_campaign_still_uses_is_refused_on_the_card_and_never_sent(
    monkeypatch,
) -> None:
    account = _Account()
    items = _items(("budget", "used_budget"))
    display = await _display(monkeypatch, account, items)

    data, _audit = await _run(monkeypatch, account, items, display)

    assert display["_checks"][_USED_BUDGET]["problem"] == (
        "Still funds Trail Running Shoes. Move it to another budget first."
    )
    assert account.mutates == []
    assert data.objects[0].outcome == "failed"
    assert account.objects[_USED_BUDGET]["status"] == "ENABLED"


async def test_an_item_added_on_the_card_after_approval_is_refused(monkeypatch) -> None:
    account = _Account()
    proposed = {"items": [_items(("budget", "unused_budget"))[0].model_dump(mode="json")]}
    items = _items(("budget", "unused_budget"), ("ad_group", "ad_group"))
    display = await _display(monkeypatch, account, items)

    with pytest.raises(ModelRetry, match="added after approval"):
        await _run(monkeypatch, account, items, display, proposed=proposed)

    assert all(body["validateOnly"] for body in account.mutates)
