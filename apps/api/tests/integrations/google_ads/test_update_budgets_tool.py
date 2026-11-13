# apps/api/tests/integrations/google_ads/test_update_budgets_tool.py

"""Changing budgets: shared budgets, moves that free a budget, decreases first, and spend."""

import re
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry

from integrations.google_ads.references import (
    GoogleAdsCampaignBudgetReference,
    GoogleAdsCampaignReference,
)
from integrations.google_ads.tools import update_budgets as tool_module
from integrations.google_ads.tools.schemas.budget_updates import GoogleAdsUpdateBudgetsOutput
from integrations.google_ads.tools.utils import edit_runs
from services.audit_events import AuditStatus
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.google_ads.support import _writable_google_ads_entry


def _budget_name(budget_id: str) -> str:
    return f"customers/111/campaignBudgets/{budget_id}"


def _campaign_name(campaign_id: str) -> str:
    return f"customers/111/campaigns/{campaign_id}"


class _Account:
    """One account's campaigns, budgets, and costs; applies `googleAds:mutate` requests."""

    def __init__(self) -> None:
        self.budgets: dict[str, dict[str, Any]] = {}
        self.campaigns: dict[str, dict[str, Any]] = {}
        self.costs: dict[str, str] = {}
        self.mutates: list[dict[str, Any]] = []

    def budget(self, budget_id: str, name: str, amount: str, *, shared: bool = False) -> None:
        self.budgets[_budget_name(budget_id)] = {
            "resourceName": _budget_name(budget_id),
            "id": budget_id,
            "name": name,
            "status": "ENABLED",
            "period": "DAILY",
            "amountMicros": amount,
            "deliveryMethod": "STANDARD",
            "explicitlyShared": shared,
        }

    def campaign(self, campaign_id: str, name: str, budget_id: str, cost: str = "") -> None:
        self.campaigns[_campaign_name(campaign_id)] = {
            "resourceName": _campaign_name(campaign_id),
            "id": campaign_id,
            "name": name,
            "status": "ENABLED",
            "experimentType": "BASE",
            "advertisingChannelType": "SEARCH",
            "campaignBudget": _budget_name(budget_id),
        }
        if cost:
            self.costs[_campaign_name(campaign_id)] = cost

    def _reference_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for campaign in self.campaigns.values():
            counts[campaign["campaignBudget"]] = counts.get(campaign["campaignBudget"], 0) + 1
        return counts

    def _search(self, query: str) -> list[dict[str, Any]]:
        ids = re.search(r"\.id IN \(([^)]*)\)", query)
        if "FROM campaign_budget" in query:
            counts = self._reference_counts()
            return [
                {"campaignBudget": {**budget, "referenceCount": str(counts.get(name, 0))}}
                for name, budget in self.budgets.items()
                if budget["id"] in ids.group(1).split(", ")
            ]
        if ids:
            return [
                {"campaign": dict(campaign)}
                for campaign in self.campaigns.values()
                if campaign["id"] in ids.group(1).split(", ")
            ]
        budgets = re.search(r"campaign_budget IN \(([^)]*)\)", query).group(1)
        on_budgets = [
            campaign
            for campaign in self.campaigns.values()
            if f"'{campaign['campaignBudget']}'" in budgets
        ]
        if "metrics.cost_micros" in query:
            return [
                {"campaign": {"resourceName": c["resourceName"]}, "metrics": {"costMicros": cost}}
                for c in on_budgets
                if (cost := self.costs.get(c["resourceName"]))
            ]
        return [{"campaign": dict(campaign)} for campaign in on_budgets]

    async def post(self, path: str, **kwargs: Any) -> Any:
        body = kwargs["json"]
        if path.endswith("googleAds:searchStream"):
            return [{"results": self._search(body["query"])}]
        self.mutates.append(body)
        responses = []
        for operation in body["mutateOperations"]:
            ((key, value),) = operation.items()
            resource = key.removesuffix("Operation")
            store = self.budgets if resource == "campaignBudget" else self.campaigns
            if "remove" in value:
                name = value["remove"]
                if not body["validateOnly"]:
                    store[name]["status"] = "REMOVED"
            else:
                update = value["update"]
                name = update["resourceName"]
                if not body["validateOnly"]:
                    for field in value["updateMask"].split(","):
                        # A nested path replaces its parent, which holds nothing else here.
                        parent = field.split(".")[0]
                        store[name][parent] = update.get(parent)
            responses.append({f"{resource}Result": {"resourceName": name}})
        return {"mutateOperationResponses": responses}


def _entry():
    entry = _writable_google_ads_entry()
    metadata = {**entry.permissions_metadata, "currency_code": "GBP", "time_zone": "Europe/London"}
    return replace(entry, permissions_metadata=metadata)


def _campaign(campaign_id: str, customer_id: str = "111") -> GoogleAdsCampaignReference:
    return GoogleAdsCampaignReference(
        customer_id=customer_id, campaign_id=campaign_id, label=f"Campaign {campaign_id}"
    )


def _budget(budget_id: str) -> GoogleAdsCampaignBudgetReference:
    return GoogleAdsCampaignBudgetReference(
        customer_id="111", budget_id=budget_id, label=f"Budget {budget_id}"
    )


def _changes(*entries: dict[str, Any]) -> list[Any]:
    return tool_module.GoogleAdsUpdateBudgetsRequest.model_validate(
        {"changes": list(entries)}
    ).changes


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
        tool_name="google_ads_update_budgets",
        tool_call_id="update-budgets-call",
    )
    result = await tool_module.google_ads_update_budgets(ctx, changes)
    return GoogleAdsUpdateBudgetsOutput.model_validate(result).results[0].data, audit


def _account() -> _Account:
    account = _Account()
    account.budget("1", "Trail Running budget", "45000000")
    account.budget("2", "Footwear Shared", "120000000", shared=True)
    account.budget("3", "Walking Socks budget", "12000000")
    account.campaign("10", "Trail Running Shoes", "1")
    account.campaign("20", "Hiking Boots", "2")
    account.campaign("21", "Gaiters", "2")
    account.campaign("30", "Walking Socks", "3")
    return account


async def test_one_approval_lowers_raises_and_moves_with_decreases_first(monkeypatch) -> None:
    account = _account()
    changes = _changes(
        {"budget": _budget("2"), "amount": "150"},
        {"campaign": _campaign("10"), "amount": "30.00"},
        {"campaign": _campaign("30"), "use_shared_budget": _budget("2")},
    )
    display = await _display(monkeypatch, account, changes)

    data, audit = await _run(monkeypatch, account, changes, display)

    shared = display["_checks"][_budget_name("2")]
    assert [item["name"] for item in shared["budget"]["campaigns"]] == ["Hiking Boots", "Gaiters"]
    assert display["_checks"][_campaign_name("30")]["removes_budget"] is True
    sent = [body for body in account.mutates if not body["validateOnly"]]
    assert [(body["mutateOperations"], body["partialFailure"]) for body in sent] == [
        (
            [
                # The decrease goes before the increase.
                {
                    "campaignBudgetOperation": {
                        "update": {"resourceName": _budget_name("1"), "amountMicros": "30000000"},
                        "updateMask": "amountMicros",
                    }
                },
                {
                    "campaignBudgetOperation": {
                        "update": {"resourceName": _budget_name("2"), "amountMicros": "150000000"},
                        "updateMask": "amountMicros",
                    }
                },
            ],
            True,
        ),
        # The move and the removal of the budget it frees succeed or fail together.
        (
            [
                {
                    "campaignOperation": {
                        "update": {
                            "resourceName": _campaign_name("30"),
                            "campaignBudget": _budget_name("2"),
                        },
                        "updateMask": "campaignBudget",
                    }
                },
                {"campaignBudgetOperation": {"remove": _budget_name("3")}},
            ],
            False,
        ),
    ]
    assert [
        (row.name, [(s.setting, s.before, s.after, s.outcome) for s in row.settings])
        for row in data.budgets
    ] == [
        ("Footwear Shared", [("amount", "120", "150", "updated")]),
        ("Trail Running Shoes", [("amount", "45", "30", "updated")]),
        (
            "Walking Socks",
            [("shared_budget", "Walking Socks budget", "Footwear Shared", "updated")],
        ),
    ]
    assert audit.await_args.kwargs["status"] == AuditStatus.SUCCESS


async def test_a_campaign_cannot_change_a_budget_another_change_already_sets(monkeypatch) -> None:
    account = _account()
    changes = _changes(
        {"campaign": _campaign("20"), "amount": "90"},
        {"budget": _budget("2"), "amount": "150"},
    )

    display = await _display(monkeypatch, account, changes)
    data, _audit = await _run(monkeypatch, account, changes, display)

    assert display["_checks"][_campaign_name("20")]["problem"] is not None
    assert display["_checks"][_budget_name("2")]["problem"] is None
    assert [row.settings[0].outcome for row in data.budgets] == ["failed", "updated"]
    assert account.budgets[_budget_name("2")]["amountMicros"] == "150000000"


async def test_a_budget_a_campaign_joined_since_approval_is_refused(monkeypatch) -> None:
    account = _account()
    changes = _changes({"campaign": _campaign("20"), "amount": "90"})
    display = await _display(monkeypatch, account, changes)
    # The approver saw the amount fund Hiking Boots and Gaiters only.
    account.campaign("40", "Trekking Poles", "2")

    data, _audit = await _run(monkeypatch, account, changes, display)

    assert [row.settings[0].outcome for row in data.budgets] == ["failed"]
    assert data.budgets[0].error_code == "CHANGED_SINCE_APPROVAL"
    assert account.budgets[_budget_name("2")]["amountMicros"] == "120000000"


_GOOGLE_FIRST = {"first": ["OWNED_AND_OPERATED"]}


async def test_a_cap_on_search_partners_is_sent_for_the_campaign_type_and_read_back(
    monkeypatch,
) -> None:
    account = _account()
    priority = {**_GOOGLE_FIRST, "then": [{"network": "SEARCH_PARTNER", "cap_percent": 20}]}
    changes = _changes({"campaign": _campaign("10"), "network_priority": priority})
    display = await _display(monkeypatch, account, changes)

    data, _audit = await _run(monkeypatch, account, changes, display)

    sent = [body["mutateOperations"] for body in account.mutates if not body["validateOnly"]]
    setting = {
        "advertisingChannelType": "SEARCH",
        "channelPriorities": [
            {"priorityTier": "TIER1", "networkChannels": ["OWNED_AND_OPERATED"]},
            {"priorityTier": "TIER2", "networkChannels": ["SEARCH_PARTNER"]},
        ],
        "budgetCaps": [{"networkChannel": "SEARCH_PARTNER", "capPercentMillis": "20000"}],
    }
    assert sent == [
        [
            {
                "campaignBudgetOperation": {
                    "update": {
                        "resourceName": _budget_name("1"),
                        "budgetNetworkSettings": {"settings": [setting]},
                    },
                    "updateMask": "budgetNetworkSettings.settings",
                }
            }
        ]
    ]
    assert [(s.before, s.after, s.outcome) for s in data.budgets[0].settings] == [
        ("ACCOUNT_DEFAULT", "OWNED_AND_OPERATED>SEARCH_PARTNER:20", "updated")
    ]


async def test_a_network_order_google_already_holds_in_its_own_layout_is_not_sent(
    monkeypatch,
) -> None:
    account = _account()
    # Google lists tiers in any order and leaves a cap of 0 out of its JSON.
    account.budgets[_budget_name("1")]["budgetNetworkSettings"] = {
        "settings": [
            {
                "advertisingChannelType": "SEARCH",
                "channelPriorities": [
                    {"priorityTier": "TIER2", "networkChannels": ["SEARCH_PARTNER"]},
                    {"priorityTier": "TIER1", "networkChannels": ["OWNED_AND_OPERATED"]},
                ],
                "budgetCaps": [{"networkChannel": "SEARCH_PARTNER"}],
            }
        ]
    }
    priority = {**_GOOGLE_FIRST, "then": [{"network": "SEARCH_PARTNER", "cap_percent": 0}]}
    changes = _changes({"campaign": _campaign("10"), "network_priority": priority})

    display = await _display(monkeypatch, account, changes)
    data, _audit = await _run(monkeypatch, account, changes, display)

    assert [s.outcome for s in data.budgets[0].settings] == ["already_set"]
    assert account.mutates == []


async def test_a_budget_google_cannot_order_networks_for_is_refused_on_the_card(
    monkeypatch,
) -> None:
    account = _account()
    account.budgets[_budget_name("2")]["budgetNetworkEligibility"] = {
        "ineligibleReasons": ["MIXED_BIDDING_STRATEGIES"]
    }
    changes = _changes({"budget": _budget("2"), "network_priority": _GOOGLE_FIRST})

    display = await _display(monkeypatch, account, changes)
    data, _audit = await _run(monkeypatch, account, changes, display)

    assert display["_checks"][_budget_name("2")]["problem"]
    assert [s.outcome for s in data.budgets[0].settings] == ["failed"]
    assert account.mutates == []


async def test_card_spend_is_the_month_cost_read_for_every_campaign_on_the_budget(
    monkeypatch,
) -> None:
    account = _account()
    account.costs = {_campaign_name("20"): "1500250000", _campaign_name("10"): "999000000"}
    changes = _changes(
        {"budget": _budget("2"), "amount": "150"},
        {"campaign": _campaign("30"), "amount": "15"},
    )

    display = await _display(monkeypatch, account, changes)

    shared = display["_checks"][_budget_name("2")]
    # Gaiters has no cost this month, and Trail Running Shoes is on another budget.
    assert shared["spend_this_month"] == "1500.25"
    assert [item["spend"] for item in shared["budget"]["campaigns"]] == ["1500.25", "0"]
    assert display["_checks"][_campaign_name("30")]["spend_this_month"] == "0"


async def test_a_campaign_from_an_account_outside_the_context_is_refused(monkeypatch) -> None:
    account = _account()
    changes = _changes({"campaign": _campaign("10", customer_id="222"), "amount": "30"})
    display = {"_checks": {}}

    with pytest.raises(ModelRetry, match="no longer in the active integration context"):
        await _run(monkeypatch, account, changes, display)

    assert account.mutates == []
