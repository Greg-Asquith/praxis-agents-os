# apps/api/tests/integrations/google_ads/test_update_conversions_tool.py

"""Changing conversion actions and account goals: checks before approval, masked writes, read-back."""

from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry

from integrations.google_ads.references import (
    GoogleAdsConversionActionReference,
    GoogleAdsConversionGoalReference,
)
from integrations.google_ads.tools import update_conversions as tool_module
from integrations.google_ads.tools.schemas.conversions import (
    GoogleAdsUpdateConversionsOutput,
    GoogleAdsUpdateConversionsRequest,
)
from integrations.google_ads.tools.utils import edit_runs
from services.audit_events import AuditStatus
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.google_ads.support import _writable_google_ads_entry

_GOAL = "customers/111/customerConversionGoals/PHONE_CALL_LEAD~CALL_FROM_ADS"


def _action_name(action_id: str) -> str:
    return f"customers/111/conversionActions/{action_id}"


def _action(action_id: str, **values: Any) -> dict[str, Any]:
    return {
        "resourceName": _action_name(action_id),
        "id": action_id,
        "name": f"Action {action_id}",
        "status": "ENABLED",
        "type": "WEBPAGE",
        "category": "SIGNUP",
        "origin": "WEBSITE",
        "ownerCustomer": "customers/111",
        "primaryForGoal": True,
        "valueSettings": {"defaultValue": 1.0, "alwaysUseDefaultValue": False},
        "countingType": "MANY_PER_CLICK",
        "clickThroughLookbackWindowDays": "30",
        "viewThroughLookbackWindowDays": "1",
        **values,
    }


class _Account:
    """One Google Ads account: answers conversion reads and applies `googleAds:mutate` requests."""

    def __init__(self, *actions: dict[str, Any]):
        self.actions = {action["resourceName"]: action for action in actions}
        self.goals = {
            _GOAL: {
                "resourceName": _GOAL,
                "category": "PHONE_CALL_LEAD",
                "origin": "CALL_FROM_ADS",
                "biddable": True,
            }
        }
        self.mutates: list[dict[str, Any]] = []

    async def post(self, path: str, **kwargs: Any) -> Any:
        body = kwargs["json"]
        if path.endswith("googleAds:searchStream"):
            query = body["query"]
            if "FROM conversion_action" in query:
                rows = [{"conversionAction": action} for action in self.actions.values()]
            elif "FROM customer_conversion_goal" in query:
                rows = [{"customerConversionGoal": goal} for goal in self.goals.values()]
            else:
                rows = [
                    {"segments": {"conversionAction": name}, "metrics": {"allConversions": 12.0}}
                    for name in self.actions
                ]
            return [{"results": rows}]
        self.mutates.append(body)
        responses = []
        for operation in body["mutateOperations"]:
            [(kind, change)] = operation.items()
            name = change["update"]["resourceName"]
            if not body["validateOnly"]:
                live = (self.actions if kind == "conversionActionOperation" else self.goals)[name]
                for path in change["updateMask"].split(","):
                    *parents, leaf = path.split(".")
                    source, target = change["update"], live
                    for part in parents:
                        source, target = source[part], target.setdefault(part, {})
                    target[leaf] = source[leaf]
            result = "conversionActionResult" if kind == "conversionActionOperation" else ""
            responses.append({result or "customerConversionGoalResult": {"resourceName": name}})
        return {"mutateOperationResponses": responses}


def _request(*changes: dict[str, Any], goals: tuple[dict[str, Any], ...] = ()) -> Any:
    return GoogleAdsUpdateConversionsRequest.model_validate(
        {
            "changes": [
                {
                    **change,
                    "conversion_action": GoogleAdsConversionActionReference(
                        customer_id="111",
                        conversion_action_id=change["conversion_action"],
                        label="Action",
                    ),
                }
                for change in changes
            ],
            "account_goals": [
                {
                    "goal": GoogleAdsConversionGoalReference(
                        customer_id="111",
                        category=goal["category"],
                        origin=goal["origin"],
                        label="Purchases",
                    ),
                    "biddable": goal["biddable"],
                }
                for goal in goals
            ],
        }
    )


def _entry():
    entry = _writable_google_ads_entry()
    metadata = {**entry.permissions_metadata, "currency_code": "GBP", "time_zone": "Europe/London"}
    return replace(entry, permissions_metadata=metadata)


async def _display(monkeypatch, account: _Account, request: Any) -> dict[str, Any]:
    monkeypatch.setattr(
        tool_module, "google_ads_client_for_principal", AsyncMock(return_value=account)
    )
    deps = SimpleNamespace(
        db=None,
        user=None,
        workspace=None,
        active_context=ResolvedActiveContext(entries=(_entry(),)),
    )
    return await tool_module._approval_display_args(deps, request.model_dump(mode="json"))


async def _run(
    monkeypatch, account: _Account, request: Any, display: dict[str, Any], *, selected: bool = True
):
    monkeypatch.setattr(edit_runs, "google_ads_client", AsyncMock(return_value=account))
    monkeypatch.setattr(tool_module, "approved_display_args", lambda _ctx: display)
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(_entry(),) if selected else ()),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name="google_ads_update_conversions",
        tool_call_id="update-conversions-call",
    )
    result = await tool_module.google_ads_update_conversions(
        ctx, request.changes, request.account_goals
    )
    return GoogleAdsUpdateConversionsOutput.model_validate(result).results[0].data, audit


async def test_one_request_masks_each_setting_group_and_an_account_goal(monkeypatch) -> None:
    account = _Account(_action("1"), _action("2"))
    request = _request(
        {"conversion_action": "1", "primary": False, "status": "ENABLED"},
        {
            "conversion_action": "2",
            "default_value": "12.50",
            "currency": "GBP",
            "always_use_default_value": True,
            "counting": "ONE_PER_CLICK",
            "click_through_days": 60,
            "view_through_days": 1,
        },
        goals=({"category": "PHONE_CALL_LEAD", "origin": "CALL_FROM_ADS", "biddable": False},),
    )
    display = await _display(monkeypatch, account, request)
    assert display["_checks"][_action_name("1")]["conversions"] == 12.0

    data, audit = await _run(monkeypatch, account, request, display)

    assert account.mutates[-1]["mutateOperations"] == [
        # Status is already Enabled, so only the goal role is masked.
        {
            "conversionActionOperation": {
                "update": {"resourceName": _action_name("1"), "primaryForGoal": False},
                "updateMask": "primaryForGoal",
            }
        },
        {
            "conversionActionOperation": {
                "update": {
                    "resourceName": _action_name("2"),
                    "valueSettings": {
                        "defaultValue": 12.5,
                        "defaultCurrencyCode": "GBP",
                        "alwaysUseDefaultValue": True,
                    },
                    "countingType": "ONE_PER_CLICK",
                    "clickThroughLookbackWindowDays": "60",
                },
                "updateMask": "valueSettings.defaultValue,valueSettings.defaultCurrencyCode,"
                "valueSettings.alwaysUseDefaultValue,countingType,clickThroughLookbackWindowDays",
            }
        },
        {
            "customerConversionGoalOperation": {
                "update": {"resourceName": _GOAL, "biddable": False},
                "updateMask": "biddable",
            }
        },
    ]
    secondary, valued, goal = data.items
    assert [(row.setting, row.before, row.after, row.outcome) for row in secondary.settings] == [
        ("status", "ENABLED", "ENABLED", "already_set"),
        ("primary", True, False, "updated"),
    ]
    assert {row.setting: (row.before, row.after) for row in valued.settings}["default_value"] == (
        "1",
        "12.5",
    )
    # A goal is named from its category and origin, not the label the model gave it.
    assert display["_checks"][_GOAL]["name"] == goal.name == "Phone call lead from call from ads"
    assert (goal.kind, goal.settings[0].after, goal.settings[0].outcome) == (
        "account_goal",
        False,
        "updated",
    )
    assert audit.await_args.kwargs["status"] == AuditStatus.SUCCESS


async def test_an_action_another_account_owns_is_refused_before_any_request(monkeypatch) -> None:
    account = _Account(_action("1", ownerCustomer="customers/999"))
    request = _request({"conversion_action": "1", "counting": "ONE_PER_CLICK"})

    display = await _display(monkeypatch, account, request)
    data, _audit = await _run(monkeypatch, account, request, display)

    assert "999" in display["_checks"][_action_name("1")]["problem"]
    assert account.mutates == []
    assert data.items[0].settings[0].outcome == "failed"
    assert account.actions[_action_name("1")]["countingType"] == "MANY_PER_CLICK"


def _sent(account: _Account) -> list[dict[str, Any]]:
    return [body for body in account.mutates if not body["validateOnly"]]


async def test_a_request_other_than_the_one_checked_is_refused(monkeypatch) -> None:
    account = _Account(_action("1"))
    display = await _display(
        monkeypatch, account, _request({"conversion_action": "1", "click_through_days": 60})
    )

    request = _request({"conversion_action": "1", "click_through_days": 90})
    data, _audit = await _run(monkeypatch, account, request, display)

    assert _sent(account) == []
    assert data.items[0].settings[0].outcome == "failed"


async def test_a_value_is_refused_when_its_currency_changed_after_the_check(monkeypatch) -> None:
    account = _Account(_action("1"))
    account.actions[_action_name("1")]["valueSettings"]["defaultCurrencyCode"] = "GBP"
    request = _request({"conversion_action": "1", "default_value": "20"})
    display = await _display(monkeypatch, account, request)
    account.actions[_action_name("1")]["valueSettings"]["defaultCurrencyCode"] = "JPY"

    data, _audit = await _run(monkeypatch, account, request, display)

    assert _sent(account) == []
    assert (data.items[0].settings[0].outcome, data.items[0].error_code) == (
        "failed",
        "CHANGED_SINCE_APPROVAL",
    )


async def test_an_account_outside_the_active_context_is_refused(monkeypatch) -> None:
    account = _Account(_action("1"))
    request = _request({"conversion_action": "1", "counting": "ONE_PER_CLICK"})
    display = await _display(monkeypatch, account, request)

    with pytest.raises(ModelRetry):
        await _run(monkeypatch, account, request, display, selected=False)

    assert _sent(account) == []
