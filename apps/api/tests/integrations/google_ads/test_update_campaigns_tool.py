# apps/api/tests/integrations/google_ads/test_update_campaigns_tool.py

"""Changing campaign settings: checks before approval, one masked request after, and read-back."""

import re
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

from integrations.google_ads.references import GoogleAdsCampaignReference
from integrations.google_ads.tools import update_campaigns as tool_module
from integrations.google_ads.tools.schemas.campaign_updates import GoogleAdsUpdateCampaignsOutput
from integrations.google_ads.tools.utils.accounts import GoogleAdsAccountFacts
from services.audit_events import AuditStatus
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.google_ads.support import _writable_google_ads_entry

_SEARCH = "customers/111/campaigns/10"
_SHOPPING = "customers/111/campaigns/11"
_DISPLAY = "customers/111/campaigns/12"
_NOT_STARTED = "customers/111/campaigns/13"
_TODAY = "2026-11-09"


def _campaign(campaign_id: str, channel: str, **values: Any) -> dict[str, Any]:
    return {
        "resourceName": f"customers/111/campaigns/{campaign_id}",
        "id": campaign_id,
        "name": f"Campaign {campaign_id}",
        "status": "ENABLED",
        "advertisingChannelType": channel,
        "startDateTime": "2026-01-01 00:00:00",
        "networkSettings": {"targetGoogleSearch": True, "targetSearchNetwork": True},
        **values,
    }


class _Account:
    """One Google Ads account: answers campaign reads and applies `googleAds:mutate` requests."""

    def __init__(self, *campaigns: dict[str, Any]):
        self.campaigns = {campaign["resourceName"]: campaign for campaign in campaigns}
        self.mutates: list[dict[str, Any]] = []

    async def post(self, path: str, **kwargs: Any) -> Any:
        body = kwargs["json"]
        if path.endswith("googleAds:searchStream"):
            ids = re.search(r"IN \(([^)]*)\)", body["query"]).group(1).split(", ")
            rows = [
                {"campaign": dict(campaign)}
                for campaign in self.campaigns.values()
                if campaign["id"] in ids
            ]
            return [{"results": rows}]
        self.mutates.append(body)
        responses = []
        for operation in body["mutateOperations"]:
            update = operation["campaignOperation"]["update"]
            name = update["resourceName"]
            if not body["validateOnly"]:
                self._apply(self.campaigns[name], update, operation["campaignOperation"])
            responses.append({"campaignResult": {"resourceName": name}})
        return {"mutateOperationResponses": responses}

    def _apply(self, campaign: dict[str, Any], update: dict[str, Any], operation: dict[str, Any]):
        for path in operation["updateMask"].split(","):
            *parents, leaf = path.split(".")
            source, target = update, campaign
            for part in parents:
                source, target = source.get(part, {}), target.setdefault(part, {})
            if leaf in source:
                target[leaf] = source[leaf]
            else:
                target.pop(leaf, None)


def _changes(*entries: dict[str, Any]) -> list[Any]:
    return tool_module.GoogleAdsUpdateCampaignsRequest.model_validate(
        {
            "changes": [
                {
                    **entry,
                    "campaign": GoogleAdsCampaignReference(
                        customer_id="111", campaign_id=entry["campaign"], label="Campaign"
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
    monkeypatch.setattr(
        GoogleAdsAccountFacts, "today", lambda _self: tool_module.date.fromisoformat(_TODAY)
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
    monkeypatch.setattr(tool_module, "google_ads_client", AsyncMock(return_value=account))
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
        tool_name="google_ads_update_campaigns",
        tool_call_id="update-campaigns-call",
    )
    result = await tool_module.google_ads_update_campaigns(ctx, changes)
    return GoogleAdsUpdateCampaignsOutput.model_validate(result).results[0].data, audit


async def test_one_request_masks_only_the_changed_settings_and_clears_an_end_date(
    monkeypatch,
) -> None:
    account = _Account(
        _campaign("10", "SEARCH"),
        _campaign("11", "SHOPPING", endDateTime="2026-12-31 23:59:59"),
    )
    changes = _changes(
        {
            "campaign": "10",
            "name": "Trail  Shoes",
            "end_date": "2027-01-31",
            "networks": {"search_partners": False, "display_expansion": False},
            "url_options": {"custom_parameters": [{"key": "season", "value": "winter"}]},
        },
        {"campaign": "11", "end_date": "none"},
    )
    display = await _display(monkeypatch, account, changes)

    data, audit = await _run(monkeypatch, account, changes, display)

    sent = account.mutates[-1]
    assert sent["validateOnly"] is False and sent["partialFailure"] is True
    assert sent["mutateOperations"] == [
        {
            "campaignOperation": {
                "update": {
                    "resourceName": _SEARCH,
                    "name": "Trail Shoes",
                    "endDateTime": "2027-01-31 23:59:59",
                    "urlCustomParameters": [{"key": "season", "value": "winter"}],
                    "networkSettings": {"targetSearchNetwork": False},
                },
                # Display expansion is already off, so it stays out of the mask.
                "updateMask": "name,endDateTime,urlCustomParameters,"
                "networkSettings.targetSearchNetwork",
            }
        },
        # The end date is in the mask and not the body, which clears it.
        {"campaignOperation": {"update": {"resourceName": _SHOPPING}, "updateMask": "endDateTime"}},
    ]
    search, shopping = data.campaigns
    rows = [row.model_dump() for row in search.settings]
    assert [(row["setting"], row["before"], row["after"], row["outcome"]) for row in rows] == [
        ("name", "Campaign 10", "Trail Shoes", "updated"),
        ("end_date", None, "2027-01-31", "updated"),
        ("custom_parameters", [], [{"key": "season", "value": "winter"}], "updated"),
        ("search_partners", True, False, "updated"),
        ("display_expansion", False, False, "already_set"),
    ]
    assert [(row.before, row.after) for row in shopping.settings] == [("2026-12-31", None)]
    assert search.read_back and shopping.read_back
    assert audit.await_args.kwargs["status"] == AuditStatus.SUCCESS


async def test_dates_and_networks_google_refuses_block_the_campaign_before_any_request(
    monkeypatch,
) -> None:
    account = _Account(
        _campaign("10", "SEARCH"),
        _campaign(
            "12",
            "DISPLAY",
            startDateTime="2026-12-01 00:00:00",
            networkSettings={"targetContentNetwork": True},
        ),
        _campaign("13", "SEARCH", startDateTime="2026-12-01 00:00:00"),
    )
    changes = _changes(
        {"campaign": "10", "start_date": "2026-12-01"},
        {"campaign": "12", "end_date": "2026-11-08", "networks": {"search_partners": True}},
        {"campaign": "13", "start_date": _TODAY},
    )

    display = await _display(monkeypatch, account, changes)

    checks = display["_checks"]
    assert [checks[name]["problems"] for name in (_SEARCH, _DISPLAY, _NOT_STARTED)] == [
        {"start_date": tool_module._STARTED},
        {
            "end_date": tool_module._END_PAST,
            "search_partners": tool_module._NETWORK["search_partners"],
        },
        {"start_date": tool_module._START_PAST},
    ]
    data, _audit = await _run(monkeypatch, account, changes, display)

    assert account.mutates == []
    assert {campaign.settings[0].outcome for campaign in data.campaigns} == {"failed"}


async def test_a_change_the_approval_check_did_not_cover_is_refused(monkeypatch) -> None:
    account = _Account(_campaign("10", "SEARCH"))
    display = await _display(monkeypatch, account, _changes({"campaign": "10", "name": "Trail"}))
    edited = _changes({"campaign": "10", "name": "Trail", "end_date": "2027-01-31"})

    data, _audit = await _run(monkeypatch, account, edited, display)

    assert [body["validateOnly"] for body in account.mutates] == [True]
    assert data.campaigns[0].message == tool_module._NOT_SHOWN
    assert account.campaigns[_SEARCH]["name"] == "Campaign 10"
