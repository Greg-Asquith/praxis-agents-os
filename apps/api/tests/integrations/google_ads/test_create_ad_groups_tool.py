# apps/api/tests/integrations/google_ads/test_create_ad_groups_tool.py

"""Creating Search ad groups: what the campaign allows, one atomic request, and its evidence."""

from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry

from core.exceptions.integration import (
    IntegrationFailureDisposition,
    IntegrationValidationError,
)
from integrations.google_ads.references import GoogleAdsCampaignReference
from integrations.google_ads.tools import create_ad_groups as tool_module
from integrations.google_ads.tools.schemas.ad_groups import (
    MAX_OBJECTS,
    GoogleAdsCreateAdGroupsOutput,
    GoogleAdsCreateAdGroupsRequest,
)
from services.audit_events import AuditStatus
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.google_ads.support import _writable_google_ads_entry

_C = "customers/111"
_RESULT_KEYS = {
    "adGroupOperation": ("adGroupResult", "adGroups"),
    "adGroupCriterionOperation": ("adGroupCriterionResult", "adGroupCriteria"),
    "adGroupAdOperation": ("adGroupAdResult", "adGroupAds"),
}


class _Account:
    """One account's campaign: answers its reads and applies `googleAds:mutate`."""

    def __init__(
        self,
        *,
        strategy: str = "MANUAL_CPC",
        channel: str = "SEARCH",
        names: tuple[str, ...] = (),
        rejected_keyword: str | None = None,
        refuse_send: bool = False,
    ):
        self.strategy = strategy
        self.channel = channel
        self.names = names
        self.rejected_keyword = rejected_keyword
        self.refuse_send = refuse_send
        self.mutates: list[dict[str, Any]] = []

    async def post(self, _path: str, **kwargs: Any) -> Any:
        body = kwargs["json"]
        if "query" in body:
            return [{"results": self._rows(body["query"])}]
        self.mutates.append(body)
        if self.refuse_send and not body["validateOnly"]:
            raise IntegrationValidationError(
                "Trademark in headline 1.",
                failure_disposition=IntegrationFailureDisposition.REJECTED,
            )
        responses, errors = [], []
        for index, operation in enumerate(body["mutateOperations"]):
            key = next(iter(operation))
            keyword = operation[key]["create"].get("keyword", {})
            if self.rejected_keyword and keyword.get("text") == self.rejected_keyword:
                responses.append({})
                errors.append(
                    {
                        "message": "Keyword text contains a symbol that isn't allowed.",
                        "errorCode": {"criterionError": "INVALID_KEYWORD_TEXT"},
                        "location": {
                            "fieldPathElements": [
                                {"fieldName": "mutate_operations", "index": index}
                            ]
                        },
                    }
                )
                continue
            result, collection = _RESULT_KEYS[key]
            suffix = f"{900 + index}" if collection == "adGroups" else f"30~{900 + index}"
            responses.append({result: {"resourceName": f"{_C}/{collection}/{suffix}"}})
        reply: dict[str, Any] = {"mutateOperationResponses": responses}
        if errors:
            reply["partialFailureError"] = {"details": [{"errors": errors}]}
        return reply

    def _rows(self, query: str) -> list[dict[str, Any]]:
        if "FROM campaign" in query:
            return [
                {
                    "campaign": {
                        "id": "10",
                        "name": "Trail",
                        "advertisingChannelType": self.channel,
                        "biddingStrategyType": self.strategy,
                    }
                }
            ]
        return [{"adGroup": {"id": "1", "name": name}} for name in self.names]


def _campaign(customer_id: str = "111") -> dict[str, Any]:
    return GoogleAdsCampaignReference(
        customer_id=customer_id, campaign_id="10", label="Trail"
    ).model_dump(mode="json")


def _ad() -> dict[str, Any]:
    return {
        "headlines": [{"text": "Trail Shoes"}, {"text": "Free Returns"}, {"text": "Grip"}],
        "descriptions": [{"text": "Lightweight trail shoes."}, {"text": "Free UK delivery."}],
        "final_url": "https://shop.test/trail",
    }


def _ad_group(name: str = "Wide Fit", **over: Any) -> dict[str, Any]:
    return {
        "name": name,
        "keywords": [
            {"text": "wide trail shoes", "match_type": "PHRASE", "cpc_bid": "0.90"},
            {"text": "wide fit runners", "match_type": "EXACT"},
        ],
        "negative_keywords": [{"text": "cheap", "match_type": "BROAD"}],
        "ads": [_ad()],
        **over,
    }


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
        tool_name="google_ads_create_ad_groups",
        tool_call_id="create-ad-groups-call",
    )
    request = GoogleAdsCreateAdGroupsRequest.model_validate(args)
    result = await tool_module.google_ads_create_ad_groups(
        ctx, request.campaign, request.ad_groups, request.status
    )
    return result, audit


async def test_one_atomic_request_creates_an_ad_group_with_its_contents_in_order(
    monkeypatch,
) -> None:
    account = _Account()
    args = {"campaign": _campaign(), "ad_groups": [_ad_group(cpc_bid="1.25")]}

    result, audit = await _run(monkeypatch, account, args)

    sent = account.mutates[-1]
    assert sent["validateOnly"] is False and sent["partialFailure"] is False
    group = f"{_C}/adGroups/-1"
    assert sent["mutateOperations"] == [
        {
            "adGroupOperation": {
                "create": {
                    "name": "Wide Fit",
                    "status": "PAUSED",
                    "type": "SEARCH_STANDARD",
                    "campaign": f"{_C}/campaigns/10",
                    "cpcBidMicros": "1250000",
                    "resourceName": group,
                }
            }
        },
        {
            "adGroupCriterionOperation": {
                "create": {
                    "adGroup": group,
                    "status": "ENABLED",
                    "keyword": {"text": "wide trail shoes", "matchType": "PHRASE"},
                    "cpcBidMicros": "900000",
                }
            }
        },
        {
            "adGroupCriterionOperation": {
                "create": {
                    "adGroup": group,
                    "status": "ENABLED",
                    "keyword": {"text": "wide fit runners", "matchType": "EXACT"},
                }
            }
        },
        {
            "adGroupCriterionOperation": {
                "create": {
                    "adGroup": group,
                    "negative": True,
                    "keyword": {"text": "cheap", "matchType": "BROAD"},
                }
            }
        },
        {
            "adGroupAdOperation": {
                "create": {
                    "adGroup": group,
                    "status": "PAUSED",
                    "ad": {
                        "finalUrls": ["https://shop.test/trail"],
                        "responsiveSearchAd": {
                            "headlines": [
                                {"text": "Trail Shoes"},
                                {"text": "Free Returns"},
                                {"text": "Grip"},
                            ],
                            "descriptions": [
                                {"text": "Lightweight trail shoes."},
                                {"text": "Free UK delivery."},
                            ],
                        },
                    },
                }
            }
        },
    ]
    data = GoogleAdsCreateAdGroupsOutput.model_validate(result).results[0].data
    assert [(row.kind, row.created) for row in data.kinds] == [
        ("ad_group", 1),
        ("keyword", 2),
        ("negative_keyword", 1),
        ("ad", 1),
    ]
    assert data.ad_groups[0].reference.ad_group_id == "900"
    assert audit.await_args.kwargs["status"] == AuditStatus.SUCCESS


async def test_a_rejected_request_records_nothing_created_and_gives_the_reason_once(
    monkeypatch,
) -> None:
    account = _Account(refuse_send=True)
    args = {"campaign": _campaign(), "ad_groups": [_ad_group()]}

    result, audit = await _run(monkeypatch, account, args)

    data = GoogleAdsCreateAdGroupsOutput.model_validate(result).results[0].data
    assert all(row.created == 0 for row in data.kinds)
    assert data.ad_groups[0].outcome == "failed" and data.ad_groups[0].reference is None
    assert [problem.kind for problem in data.problems] == ["ad_group"]
    assert "Trademark in headline 1." in data.problems[0].message
    assert audit.await_args.kwargs["status"] == AuditStatus.FAILURE


async def test_approval_reports_what_the_campaign_allows_and_keeps_refused_groups_out_of_the_dry_run(
    monkeypatch,
) -> None:
    account = _Account(
        strategy="MAXIMIZE_CONVERSIONS",
        names=("Trail Shoes",),
        rejected_keyword="wide fit runners",
    )
    plain = _ad_group()
    plain["keywords"] = [{"text": "wide fit runners", "match_type": "EXACT"}]
    args = {
        "campaign": _campaign(),
        "ad_groups": [
            plain,
            {**plain, "name": "trail shoes"},
            {**plain, "name": "Sale", "cpc_bid": "0.90"},
        ],
    }

    checks = (await _display(monkeypatch, account, args))["_checks"]

    assert checks["campaign"]["strategy_name"] == "Maximise Conversions"
    assert checks["campaign"]["accepts_cpc_bid"] is False
    assert checks["existing_names"] == ["Trail Shoes"]
    sent_names = [
        operation["adGroupOperation"]["create"]["name"]
        for operation in account.mutates[0]["mutateOperations"]
        if "adGroupOperation" in operation
    ]
    assert account.mutates[0]["validateOnly"] is True
    assert sent_names == ["Wide Fit"]
    assert checks["problems"] == [
        {
            "ad_group": "Wide Fit",
            "kind": "keyword",
            "text": "wide fit runners",
            "match_type": "EXACT",
            "message": "Google says: Keyword text contains a symbol that isn't allowed.",
        }
    ]


async def test_a_click_bid_the_strategy_ignores_is_refused_after_approval_with_nothing_sent(
    monkeypatch,
) -> None:
    account = _Account(strategy="MAXIMIZE_CONVERSIONS")
    args = {"campaign": _campaign(), "ad_groups": [_ad_group(cpc_bid="0.90")]}

    result, _audit = await _run(monkeypatch, account, args)

    entry = GoogleAdsCreateAdGroupsOutput.model_validate(result).results[0]
    assert entry.status == "error"
    assert "the campaign uses Maximise Conversions" in entry.error_message
    assert account.mutates == []


async def test_a_campaign_outside_search_is_refused_with_nothing_sent(monkeypatch) -> None:
    account = _Account(channel="DISPLAY")
    args = {"campaign": _campaign(), "ad_groups": [_ad_group()]}

    result, _audit = await _run(monkeypatch, account, args)

    entry = GoogleAdsCreateAdGroupsOutput.model_validate(result).results[0]
    assert entry.status == "error"
    assert "only go in Search campaigns" in entry.error_message
    assert account.mutates == []


async def test_a_campaign_in_an_account_outside_the_context_is_refused(monkeypatch) -> None:
    account = _Account()
    args = {"campaign": _campaign(customer_id="222"), "ad_groups": [_ad_group()]}

    with pytest.raises(ModelRetry, match="no longer in the active integration context"):
        await _run(monkeypatch, account, args)

    assert account.mutates == []


async def test_a_build_at_the_object_limit_fits_one_audit_event(monkeypatch) -> None:
    account = _Account()
    long_text = "wörterbücher " * 5
    groups = [
        {
            "name": f"{'Ä' * 240} {group}",
            "keywords": [
                {"text": f"{long_text[:70]} {group} {index}", "match_type": "PHRASE"}
                for index in range(125 - 1)
            ],
        }
        for group in range(20)
    ]
    args = {"campaign": _campaign(), "ad_groups": groups}
    assert sum(1 + len(group["keywords"]) for group in groups) == MAX_OBJECTS

    result, audit = await _run(monkeypatch, account, args)

    assert GoogleAdsCreateAdGroupsOutput.model_validate(result).results[0].status == "success"
    assert audit.await_args.kwargs["status"] == AuditStatus.SUCCESS
