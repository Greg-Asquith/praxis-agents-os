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
from integrations.google_ads.tools.utils import edit_runs
from integrations.google_ads.tools.utils.accounts import GoogleAdsAccountFacts
from services.audit_events import AuditStatus
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.google_ads.support import _writable_google_ads_entry

_SEARCH = "customers/111/campaigns/10"
_SHOPPING = "customers/111/campaigns/11"
_DISPLAY = "customers/111/campaigns/12"
_NOT_STARTED = "customers/111/campaigns/13"
_SMART = "customers/111/campaigns/14"
# Members of Google's bidding oneof, and the type each sets.
_BIDDING = {
    "manualCpc": "MANUAL_CPC",
    "targetSpend": "TARGET_SPEND",
    "maximizeConversions": "MAXIMIZE_CONVERSIONS",
    "maximizeConversionValue": "MAXIMIZE_CONVERSION_VALUE",
}
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
        self.ad_groups: list[dict[str, Any]] = []
        self.conversions: dict[str, float] = {}
        # Each campaign's goal level, and whether each of its goals bids, by `category~origin`.
        self.goal_levels: dict[str, str] = {}
        self.goals: dict[str, dict[str, bool]] = {}

    async def post(self, path: str, **kwargs: Any) -> Any:
        body = kwargs["json"]
        if "FROM ad_group" in body.get("query", ""):
            return [{"results": self.ad_groups}]
        if "metrics.conversions" in body.get("query", ""):
            rows = [
                {"campaign": {"id": key}, "metrics": {"conversions": value}}
                for key, value in self.conversions.items()
            ]
            return [{"results": rows}]
        if "FROM conversion_goal_campaign_config" in body.get("query", ""):
            rows = [
                {
                    "campaign": {"id": key},
                    "conversionGoalCampaignConfig": {"goalConfigLevel": level},
                }
                for key, level in self.goal_levels.items()
            ]
            return [{"results": rows}]
        if "FROM campaign_conversion_goal" in body.get("query", ""):
            rows = [
                {
                    "campaign": {"id": key},
                    "campaignConversionGoal": {
                        "category": goal.split("~")[0],
                        "origin": goal.split("~")[1],
                        "biddable": biddable,
                    },
                }
                for key, goals in self.goals.items()
                for goal, biddable in goals.items()
            ]
            return [{"results": rows}]
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
            ((kind, item),) = operation.items()
            if kind != "campaignOperation" and body["partialFailure"]:
                raise AssertionError("Google refuses goal operations with partial failure")
            update = item["update"]
            name = update["resourceName"]
            if not body["validateOnly"]:
                self._write(kind, name, update, item)
            responses.append({kind.replace("Operation", "Result"): {"resourceName": name}})
        return {"mutateOperationResponses": responses}

    def _write(self, kind: str, name: str, update: dict[str, Any], item: dict[str, Any]) -> None:
        key = name.rsplit("/", 1)[1]
        if kind == "campaignOperation":
            self._apply(self.campaigns[name], update, item)
        elif kind == "conversionGoalCampaignConfigOperation":
            self.goal_levels[key] = update["goalConfigLevel"]
        else:
            campaign_id, goal = key.split("~", 1)
            self.goals[campaign_id][goal] = update["biddable"]

    def _apply(self, campaign: dict[str, Any], update: dict[str, Any], operation: dict[str, Any]):
        for path in operation["updateMask"].split(","):
            root = path.split(".")[0]
            if path in _BIDDING and update.get(path):
                raise AssertionError(f"Google refuses a mask on a field with subfields: {path}")
            if root in _BIDDING and campaign.get("biddingStrategyType") != _BIDDING[root]:
                # Setting one member of the oneof clears the others.
                for member in _BIDDING:
                    campaign.pop(member, None)
                campaign["biddingStrategyType"] = _BIDDING[root]
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
            "search_partners": tool_module._WRONG_CHANNEL["search_partners"],
        },
        {"start_date": tool_module._START_PAST},
    ]
    data, _audit = await _run(monkeypatch, account, changes, display)

    assert account.mutates == []
    assert {campaign.settings[0].outcome for campaign in data.campaigns} == {"failed"}


async def test_video_pages_keep_the_campaign_s_other_automation_and_are_refused_on_search(
    monkeypatch,
) -> None:
    expansion_off = {
        "assetAutomationType": "FINAL_URL_EXPANSION_TEXT_ASSET_AUTOMATION",
        "assetAutomationStatus": "OPTED_OUT",
    }
    pmax = "customers/111/campaigns/15"
    account = _Account(
        _campaign("10", "SEARCH"),
        _campaign("15", "PERFORMANCE_MAX", assetAutomationSettings=[expansion_off]),
    )
    pages = ["https://www.youtube.com/@northwind", "https://northwind.example/films"]
    changes = _changes(
        {"campaign": "10", "video_pages": pages}, {"campaign": "15", "video_pages": pages}
    )
    display = await _display(monkeypatch, account, changes)

    data, _audit = await _run(monkeypatch, account, changes, display)

    assert display["_checks"][_SEARCH]["problems"] == {
        "video_pages": tool_module._WRONG_CHANNEL["video_pages"]
    }
    # Google replaces the whole list, so the opt-out the campaign already has goes back with it.
    assert account.mutates[-1]["mutateOperations"] == [
        {
            "campaignOperation": {
                "update": {
                    "resourceName": pmax,
                    "assetAutomationSettings": [
                        {
                            "assetAutomationType": "AUTOMATED_VIDEO_CRAWL",
                            "assetAutomationStatus": "OPTED_IN",
                            "automatedVideoCrawlSetting": {
                                "automatedVideoCrawlInfos": [
                                    {
                                        "url": "https://northwind.example/films",
                                        "sourcePlatform": "LANDING_PAGE",
                                        "enabled": True,
                                    },
                                    {
                                        "url": "https://www.youtube.com/@northwind",
                                        "sourcePlatform": "YOUTUBE",
                                        "enabled": True,
                                    },
                                ]
                            },
                        },
                        expansion_off,
                    ],
                },
                "updateMask": "assetAutomationSettings",
            }
        }
    ]
    search, performance_max = data.campaigns
    assert search.settings[0].outcome == "failed"
    row = performance_max.settings[0]
    assert (row.before, row.after, row.outcome) == ([], sorted(pages), "updated")

    off = _changes({"campaign": "15", "video_pages": []})
    await _run(monkeypatch, account, off, await _display(monkeypatch, account, off))

    assert account.campaigns[pmax]["assetAutomationSettings"] == [
        {"assetAutomationType": "AUTOMATED_VIDEO_CRAWL", "assetAutomationStatus": "OPTED_OUT"},
        expansion_off,
    ]


async def test_a_change_the_approval_check_did_not_cover_is_refused(monkeypatch) -> None:
    account = _Account(_campaign("10", "SEARCH"))
    display = await _display(monkeypatch, account, _changes({"campaign": "10", "name": "Trail"}))
    edited = _changes({"campaign": "10", "name": "Trail", "end_date": "2027-01-31"})

    data, _audit = await _run(monkeypatch, account, edited, display)

    assert [body["validateOnly"] for body in account.mutates] == [True]
    assert data.campaigns[0].message == tool_module.NOT_SHOWN
    assert account.campaigns[_SEARCH]["name"] == "Campaign 10"


async def test_a_new_strategy_is_sent_whole_and_a_target_change_alone(monkeypatch) -> None:
    account = _Account(
        _campaign("10", "SEARCH", biddingStrategyType="MANUAL_CPC", manualCpc={}),
        _campaign(
            "14",
            "SEARCH",
            biddingStrategyType="MAXIMIZE_CONVERSIONS",
            maximizeConversions={"targetCpaMicros": "15000000"},
        ),
    )
    account.ad_groups = [
        {"campaign": {"id": "10"}, "adGroup": {"name": "Boots", "cpcBidMicros": "500000"}}
    ]
    account.conversions = {"10": 42.0}
    changes = _changes(
        {"campaign": "10", "bidding": {"strategy": "MAXIMIZE_CONVERSIONS", "target_cpa": "18.00"}},
        {"campaign": "14", "bidding": {"strategy": "TARGETS", "target_cpa": "20"}},
    )
    display = await _display(monkeypatch, account, changes)

    data, _audit = await _run(monkeypatch, account, changes, display)

    assert account.mutates[-1]["mutateOperations"] == [
        {
            "campaignOperation": {
                "update": {
                    "resourceName": _SEARCH,
                    "maximizeConversions": {"targetCpaMicros": "18000000"},
                },
                # Setting a field inside another strategy moves the campaign off Manual CPC.
                "updateMask": "maximizeConversions.targetCpaMicros",
            }
        },
        {
            "campaignOperation": {
                "update": {
                    "resourceName": _SMART,
                    "maximizeConversions": {"targetCpaMicros": "20000000"},
                },
                "updateMask": "maximizeConversions.targetCpaMicros",
            }
        },
    ]
    checks = display["_checks"]
    assert checks[_SEARCH]["learning"] and not checks[_SMART]["learning"]
    assert checks[_SEARCH]["notes"]["bidding"] == [
        "42 conversions in the last 30 days.",
        "Google sets bids itself, so the CPC bids on 1 ad group stop being used.",
    ]
    assert [
        (
            row.before.model_dump(exclude_none=True),
            row.after.model_dump(exclude_none=True),
            row.outcome,
        )
        for c in data.campaigns
        for row in c.settings
    ] == [
        (
            {"strategy": "MANUAL_CPC"},
            {"strategy": "MAXIMIZE_CONVERSIONS", "target_cpa": "18"},
            "updated",
        ),
        (
            {"strategy": "MAXIMIZE_CONVERSIONS", "target_cpa": "15"},
            {"strategy": "MAXIMIZE_CONVERSIONS", "target_cpa": "20"},
            "updated",
        ),
    ]


async def test_a_target_the_current_strategy_does_not_take_is_refused_before_any_request(
    monkeypatch,
) -> None:
    account = _Account(
        _campaign("10", "SEARCH", biddingStrategyType="TARGET_SPEND", targetSpend={})
    )
    changes = _changes({"campaign": "10", "bidding": {"strategy": "TARGETS", "target_roas": 4}})

    display = await _display(monkeypatch, account, changes)
    data, _audit = await _run(monkeypatch, account, changes, display)

    assert display["_checks"][_SEARCH]["problems"]["bidding"].startswith(
        "Target ROAS needs Maximise Conversion Value."
    )
    assert account.mutates == []
    assert data.campaigns[0].settings[0].outcome == "failed"


async def test_a_strategy_changed_since_approval_is_not_replaced(monkeypatch) -> None:
    account = _Account(_campaign("10", "SEARCH", biddingStrategyType="MANUAL_CPC", manualCpc={}))
    changes = _changes({"campaign": "10", "bidding": {"strategy": "MAXIMIZE_CONVERSIONS"}})
    display = await _display(monkeypatch, account, changes)
    # Someone moves the campaign to Maximise Clicks after the card was checked.
    campaign = account.campaigns[_SEARCH]
    campaign.pop("manualCpc")
    campaign.update(biddingStrategyType="TARGET_SPEND", targetSpend={})

    data, _audit = await _run(monkeypatch, account, changes, display)

    assert [body["validateOnly"] for body in account.mutates] == [True]
    assert data.campaigns[0].error_code == "CHANGED_SINCE_APPROVAL"


async def test_expansion_and_text_customisation_share_one_automation_list(monkeypatch) -> None:
    pmax, kept_on = "customers/111/campaigns/15", "customers/111/campaigns/16"
    account = _Account(_campaign("15", "PERFORMANCE_MAX"), _campaign("16", "PERFORMANCE_MAX"))
    changes = _changes(
        {"campaign": "15", "final_url_expansion": False, "text_customisation": False},
        {"campaign": "16", "text_customisation": False},
    )
    display = await _display(monkeypatch, account, changes)

    data, _audit = await _run(monkeypatch, account, changes, display)

    # Google keeps text customisation on while final URL expansion is on.
    assert display["_checks"][kept_on]["problems"] == {
        "text_customisation": tool_module._TEXT_WITH_EXPANSION
    }
    assert account.mutates[-1]["mutateOperations"] == [
        {
            "campaignOperation": {
                "update": {
                    "resourceName": pmax,
                    "assetAutomationSettings": [
                        {
                            "assetAutomationType": "FINAL_URL_EXPANSION_TEXT_ASSET_AUTOMATION",
                            "assetAutomationStatus": "OPTED_OUT",
                        },
                        {
                            "assetAutomationType": "TEXT_ASSET_AUTOMATION",
                            "assetAutomationStatus": "OPTED_OUT",
                        },
                    ],
                },
                "updateMask": "assetAutomationSettings",
            }
        }
    ]
    changed, refused = data.campaigns
    assert [(row.setting, row.before, row.after, row.outcome) for row in changed.settings] == [
        ("final_url_expansion", True, False, "updated"),
        ("text_customisation", True, False, "updated"),
    ]
    assert refused.settings[0].outcome == "failed"


async def test_campaign_goals_change_together_and_go_back_to_the_account_s(monkeypatch) -> None:
    account = _Account(_campaign("10", "SEARCH"), _campaign("11", "SHOPPING"))
    account.goal_levels = {"10": "CUSTOMER", "11": "CAMPAIGN"}
    account.goals = {
        "10": {"PURCHASE~WEBSITE": True, "SIGNUP~WEBSITE": True},
        "11": {"PURCHASE~WEBSITE": True, "SIGNUP~WEBSITE": False},
    }
    changes = _changes(
        {"campaign": "10", "conversion_goals": [{"category": "PURCHASE", "origin": "WEBSITE"}]},
        {"campaign": "11", "conversion_goals": "account"},
    )
    display = await _display(monkeypatch, account, changes)

    data, audit = await _run(monkeypatch, account, changes, display)

    goals = "customers/111/campaignConversionGoals"
    configs = "customers/111/conversionGoalCampaignConfigs"
    # Each campaign's goals go in their own request, which Google applies whole or not at all.
    assert [
        (body["partialFailure"], body["mutateOperations"]) for body in account.mutates[-2:]
    ] == [
        (
            False,
            [
                {
                    "conversionGoalCampaignConfigOperation": {
                        "update": {"resourceName": f"{configs}/10", "goalConfigLevel": "CAMPAIGN"},
                        "updateMask": "goalConfigLevel",
                    }
                },
                # Purchases already bid, so only the goal that stops is sent.
                {
                    "campaignConversionGoalOperation": {
                        "update": {"resourceName": f"{goals}/10~SIGNUP~WEBSITE", "biddable": False},
                        "updateMask": "biddable",
                    }
                },
            ],
        ),
        (
            False,
            [
                {
                    "conversionGoalCampaignConfigOperation": {
                        "update": {"resourceName": f"{configs}/11", "goalConfigLevel": "CUSTOMER"},
                        "updateMask": "goalConfigLevel",
                    }
                }
            ],
        ),
    ]
    purchases = [{"category": "PURCHASE", "origin": "WEBSITE"}]
    assert [
        (
            row.before if isinstance(row.before, str) else [g.model_dump() for g in row.before],
            row.after if isinstance(row.after, str) else [g.model_dump() for g in row.after],
            row.outcome,
        )
        for campaign in data.campaigns
        for row in campaign.settings
    ] == [("account", purchases, "updated"), (purchases, "account", "updated")]
    assert all(campaign.read_back for campaign in data.campaigns)
    assert audit.await_args.kwargs["status"] == AuditStatus.SUCCESS


async def test_goals_are_refused_when_unknown_or_changed_since_approval(monkeypatch) -> None:
    account = _Account(_campaign("10", "SEARCH"), _campaign("11", "SHOPPING"))
    account.goal_levels = {"10": "CUSTOMER", "11": "CUSTOMER"}
    account.goals = {
        "10": {"PURCHASE~WEBSITE": True},
        "11": {"PURCHASE~WEBSITE": True, "SIGNUP~WEBSITE": True},
    }
    purchases = [{"category": "PURCHASE", "origin": "WEBSITE"}]
    changes = _changes(
        {"campaign": "10", "conversion_goals": [{"category": "STORE_VISIT", "origin": "STORE"}]},
        {"campaign": "11", "conversion_goals": purchases},
    )
    display = await _display(monkeypatch, account, changes)
    # Someone stops purchases bidding in the second campaign after the card was checked.
    account.goals["11"]["PURCHASE~WEBSITE"] = False

    data, _audit = await _run(monkeypatch, account, changes, display)

    assert display["_checks"][_SEARCH]["problems"] == {
        "conversion_goals": "Store visit from store isn't one of the account's conversion goals."
    }
    assert all(body["validateOnly"] for body in account.mutates)
    unknown, stale = data.campaigns
    assert unknown.settings[0].outcome == "failed"
    assert stale.error_code == "CHANGED_SINCE_APPROVAL"
    assert account.goal_levels["11"] == "CUSTOMER"
