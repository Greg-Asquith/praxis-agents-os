# apps/api/tests/integrations/google_ads/test_update_negative_keywords_tool.py

"""Negative keywords on campaigns, ad groups, and lists: checks before approval, then one send."""

import re
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from integrations.google_ads.tools import update_negative_keywords as tool_module
from integrations.google_ads.tools.schemas.negative_keywords import (
    GoogleAdsUpdateNegativeKeywordsOutput,
    GoogleAdsUpdateNegativeKeywordsRequest,
)
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.google_ads.support import _writable_google_ads_entry

_C = "customers/111"


class _Account:
    """One Google Ads account: answers negative keyword reads and applies mutate requests."""

    def __init__(self) -> None:
        self.campaigns = {"10": "Trail", "20": "Road", "30": "Kids"}
        self.ad_groups = {"40": ("Trail Shoes", "10")}
        self.lists = {"50": "Brand Protection"}
        # (collection, owner ID, text, match type) by resource name.
        self.negatives: dict[str, tuple[str, str, str, str]] = {
            f"{_C}/adGroupCriteria/40~7": ("adGroups", "40", "cheap", "BROAD"),
        }
        self.uses: set[tuple[str, str]] = set()
        self.bid_keywords = [("10", "40", "Trail Shoes", "trail running shoes")]
        self.mutates: list[dict[str, Any]] = []
        self.next_id = 900

    async def post(self, path: str, **kwargs: Any) -> Any:
        body = kwargs["json"]
        if path.endswith("googleAds:searchStream"):
            return [{"results": self._search(body["query"])}]
        assert path == f"{_C}/googleAds:mutate"
        self.mutates.append(body)
        return self._mutate(body)

    def _search(self, query: str) -> list[dict[str, Any]]:
        match = re.search(r"IN \(([^)]*)\)", query)
        ids = set(re.findall(r"\d+", match.group(1))) if match else set()
        resource = re.search(r"FROM (\w+)", query).group(1)
        if resource == "campaign":
            return [
                {"campaign": {"id": key, "name": name, "status": "ENABLED"}}
                for key, name in self.campaigns.items()
                if key in ids
            ]
        if resource == "ad_group":
            return [
                {
                    "adGroup": {"id": key, "name": name, "status": "ENABLED"},
                    "campaign": {"id": campaign},
                }
                for key, (name, campaign) in self.ad_groups.items()
                if key in ids
            ]
        if resource == "shared_set":
            return [
                {"sharedSet": {"id": key, "name": name, "status": "ENABLED"}}
                for key, name in self.lists.items()
            ]
        if resource == "ad_group_criterion" and "negative = FALSE" in query:
            field = "campaign" if "campaign.id IN" in query else "ad_group"
            return [
                {
                    "campaign": {"id": campaign},
                    "adGroup": {"id": ad_group, "name": name},
                    "adGroupCriterion": {"keyword": {"text": text}},
                }
                for campaign, ad_group, name, text in self.bid_keywords
                if (campaign if field == "campaign" else ad_group) in ids
            ]
        if resource == "campaign_shared_set":
            return [
                {
                    "campaignSharedSet": {
                        "resourceName": f"{_C}/campaignSharedSets/{campaign}~{shared_set}",
                        "campaign": f"{_C}/campaigns/{campaign}",
                        "sharedSet": f"{_C}/sharedSets/{shared_set}",
                    }
                }
                for campaign, shared_set in self.uses
                if shared_set in ids
            ]
        collection, row_key, owner_key = {
            "campaign_criterion": ("campaigns", "campaignCriterion", "campaign"),
            "ad_group_criterion": ("adGroups", "adGroupCriterion", "adGroup"),
            "shared_criterion": ("sharedSets", "sharedCriterion", "sharedSet"),
        }[resource]
        return [
            {
                owner_key: {"id": owner},
                row_key: {
                    "resourceName": name,
                    "keyword": {"text": text, "matchType": match_type},
                },
            }
            for name, (kind, owner, text, match_type) in self.negatives.items()
            if kind == collection and owner in ids
        ]

    def _mutate(self, body: dict[str, Any]) -> dict[str, Any]:
        created: dict[str, str] = {}
        responses = []
        for operation in body["mutateOperations"]:
            ((key, value),) = operation.items()
            name = self._apply(key.removesuffix("Operation"), value, created, body["validateOnly"])
            responses.append({key.replace("Operation", "Result"): {"resourceName": name}})
        return {"mutateOperationResponses": responses}

    def _apply(self, resource: str, value: dict, created: dict, dry: bool) -> str:
        if "remove" in value:
            if not dry:
                self.negatives.pop(value["remove"], None)
            return value["remove"]
        create = {
            key: created.get(item, item) if isinstance(item, str) else item
            for key, item in value["create"].items()
        }
        self.next_id += 1
        if resource == "sharedSet":
            name = f"{_C}/sharedSets/{self.next_id}"
            created[create["resourceName"]] = name
            if not dry:
                self.lists[str(self.next_id)] = create["name"]
            return name
        if resource == "campaignSharedSet":
            campaign, shared_set = (create[k].rsplit("/", 1)[1] for k in ("campaign", "sharedSet"))
            if not dry:
                self.uses.add((campaign, shared_set))
            return f"{_C}/campaignSharedSets/{campaign}~{shared_set}"
        owner_field, collection, criteria = {
            "campaignCriterion": ("campaign", "campaigns", "campaignCriteria"),
            "adGroupCriterion": ("adGroup", "adGroups", "adGroupCriteria"),
            "sharedCriterion": ("sharedSet", "sharedSets", "sharedCriteria"),
        }[resource]
        owner = create[owner_field].rsplit("/", 1)[1]
        name = f"{_C}/{criteria}/{owner}~{self.next_id}"
        if not dry:
            keyword = create["keyword"]
            self.negatives[name] = (collection, owner, keyword["text"], keyword["matchType"])
        return name


def _campaign(campaign_id: str, label: str = "Campaign") -> dict[str, Any]:
    return {"customer_id": "111", "campaign_id": campaign_id, "label": label}


def _keywords(*items: tuple[str, str]) -> list[dict[str, str]]:
    return [{"text": text, "match_type": match_type} for text, match_type in items]


def _args(*entries: dict[str, Any]) -> dict[str, Any]:
    return GoogleAdsUpdateNegativeKeywordsRequest.model_validate(
        {"entries": list(entries)}
    ).model_dump(mode="json")


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


async def _run(
    monkeypatch,
    account: _Account,
    args: dict[str, Any],
    display: dict[str, Any],
):
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
        tool_name="google_ads_update_negative_keywords",
        tool_call_id="update-negative-keywords-call",
    )
    entries = GoogleAdsUpdateNegativeKeywordsRequest.model_validate(args).entries
    result = await tool_module.google_ads_update_negative_keywords(ctx, entries)
    shown = result.metadata["public_result"]
    GoogleAdsUpdateNegativeKeywordsOutput.model_validate(result.return_value)
    return GoogleAdsUpdateNegativeKeywordsOutput.model_validate(shown).model_dump(mode="json")


def _outcomes(result: dict[str, Any]) -> set[tuple[str, str, str, str]]:
    return {
        (row["target_name"], row["action"], row["name"], row["outcome"])
        for row in result["results"][0]["data"]["outcomes"]
    }


async def test_one_approval_changes_campaigns_an_ad_group_a_list_and_starts_a_new_list(
    monkeypatch,
) -> None:
    account = _Account()
    args = _args(
        {"kind": "campaign", "campaign": _campaign("10"), "add": _keywords(("jobs", "BROAD"))},
        {"kind": "campaign", "campaign": _campaign("20"), "add": _keywords(("free", "PHRASE"))},
        {
            "kind": "ad_group",
            "ad_group": {**_campaign("10"), "ad_group_id": "40", "label": "Trail Shoes"},
            "remove": _keywords(("cheap", "BROAD")),
        },
        {
            "kind": "list",
            "negative_list": {"customer_id": "111", "shared_set_id": "50", "label": "Brand"},
            "add": _keywords(("repair", "EXACT")),
            "apply_to_campaigns": [_campaign("20")],
        },
        {
            "kind": "new_list",
            "new_list": "Competitor Brands",
            "add": _keywords(("salomon", "PHRASE")),
            "apply_to_campaigns": [_campaign("30")],
        },
    )

    display = await _display(monkeypatch, account, args)
    checks = display["_checks"]
    assert [check["problem"] for check in checks.values()] == [None] * 5
    assert all(row["problem"] is None for check in checks.values() for row in check["rows"])
    # Google checks the edits, then the new list, without changing anything.
    assert [body["validateOnly"] for body in account.mutates] == [True, True]

    result = await _run(monkeypatch, account, args, display)

    edits, build = account.mutates[2:]
    assert edits["partialFailure"] is True
    assert edits["mutateOperations"] == [
        {
            "campaignCriterionOperation": {
                "create": {
                    "campaign": f"{_C}/campaigns/10",
                    "keyword": {"text": "jobs", "matchType": "BROAD"},
                    "negative": True,
                }
            }
        },
        {
            "campaignCriterionOperation": {
                "create": {
                    "campaign": f"{_C}/campaigns/20",
                    "keyword": {"text": "free", "matchType": "PHRASE"},
                    "negative": True,
                }
            }
        },
        {"adGroupCriterionOperation": {"remove": f"{_C}/adGroupCriteria/40~7"}},
        {
            "sharedCriterionOperation": {
                "create": {
                    "sharedSet": f"{_C}/sharedSets/50",
                    "keyword": {"text": "repair", "matchType": "EXACT"},
                }
            }
        },
        {
            "campaignSharedSetOperation": {
                "create": {"campaign": f"{_C}/campaigns/20", "sharedSet": f"{_C}/sharedSets/50"}
            }
        },
    ]
    # The new list, its keyword, and its campaign succeed or fail together.
    assert build["partialFailure"] is False
    assert build["mutateOperations"] == [
        {
            "sharedSetOperation": {
                "create": {
                    "name": "Competitor Brands",
                    "type": "NEGATIVE_KEYWORDS",
                    "resourceName": f"{_C}/sharedSets/-1",
                }
            }
        },
        {
            "sharedCriterionOperation": {
                "create": {
                    "keyword": {"text": "salomon", "matchType": "PHRASE"},
                    "sharedSet": f"{_C}/sharedSets/-1",
                }
            }
        },
        {
            "campaignSharedSetOperation": {
                "create": {"campaign": f"{_C}/campaigns/30", "sharedSet": f"{_C}/sharedSets/-1"}
            }
        },
    ]
    assert _outcomes(result) == {
        ("Trail", "add", "jobs", "added"),
        ("Road", "add", "free", "added"),
        ("Trail Shoes", "remove", "cheap", "removed"),
        ("Brand Protection", "add", "repair", "added"),
        ("Brand Protection", "add", "Road", "added"),
        ("Competitor Brands", "create", "Competitor Brands", "created"),
        ("Competitor Brands", "add", "salomon", "added"),
        ("Competitor Brands", "add", "Kids", "added"),
    }


async def test_a_negative_already_in_place_is_already_set_and_sends_nothing(monkeypatch) -> None:
    account = _Account()
    account.negatives[f"{_C}/campaignCriteria/10~5"] = ("campaigns", "10", "Jobs", "BROAD")
    args = _args(
        {"kind": "campaign", "campaign": _campaign("10"), "add": _keywords(("jobs", "BROAD"))}
    )

    display = await _display(monkeypatch, account, args)
    result = await _run(monkeypatch, account, args, display)

    assert account.mutates == []
    assert _outcomes(result) == {("Trail", "add", "jobs", "already_set")}


async def test_a_negative_that_blocks_a_keyword_bid_on_is_a_problem_and_never_sent(
    monkeypatch,
) -> None:
    account = _Account()
    args = _args(
        {
            "kind": "campaign",
            "campaign": _campaign("10"),
            "add": _keywords(("running shoes", "PHRASE"), ("jobs", "BROAD")),
        }
    )

    display = await _display(monkeypatch, account, args)
    rows = {row["name"]: row["problem"] for row in display["_checks"][f"{_C}/campaigns/10"]["rows"]}
    assert rows == {
        "running shoes": "Blocks “trail running shoes”, a keyword you bid on in Trail Shoes.",
        "jobs": None,
    }

    result = await _run(monkeypatch, account, args, display)

    sent = account.mutates[-1]["mutateOperations"]
    assert [op["campaignCriterionOperation"]["create"]["keyword"]["text"] for op in sent] == [
        "jobs"
    ]
    assert ("Trail", "add", "running shoes", "failed") in _outcomes(result)


async def test_a_list_cannot_be_applied_to_a_campaign_in_another_account() -> None:
    with pytest.raises(ValueError, match="campaigns in its own account"):
        _args(
            {
                "kind": "list",
                "negative_list": {"customer_id": "111", "shared_set_id": "50", "label": "Brand"},
                "apply_to_campaigns": [{"customer_id": "222", "campaign_id": "10", "label": "X"}],
            }
        )


async def test_a_campaign_added_on_the_card_is_not_sent_until_google_checked_it(
    monkeypatch,
) -> None:
    account = _Account()
    proposed = _args(
        {"kind": "campaign", "campaign": _campaign("10"), "add": _keywords(("jobs", "BROAD"))}
    )
    edited = _args(
        {"kind": "campaign", "campaign": _campaign("10"), "add": _keywords(("jobs", "BROAD"))},
        {"kind": "campaign", "campaign": _campaign("20"), "add": _keywords(("jobs", "BROAD"))},
    )
    # The approver saw the request before the second campaign was added.
    display = await _display(monkeypatch, account, proposed)

    result = await _run(monkeypatch, account, edited, display)

    sent = account.mutates[-1]["mutateOperations"]
    assert [op["campaignCriterionOperation"]["create"]["campaign"] for op in sent] == [
        f"{_C}/campaigns/10"
    ]
    assert ("Campaign", "add", "jobs", "failed") in _outcomes(result)
