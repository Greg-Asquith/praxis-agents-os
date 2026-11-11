# apps/api/tests/integrations/google_ads/test_create_keywords_tool.py

"""Adding keywords per ad group: checks before approval, the request sent, and refusals."""

from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

from integrations.google_ads.references import GoogleAdsAdGroupReference
from integrations.google_ads.tools import create_keywords as tool_module
from integrations.google_ads.tools.schemas.keyword_additions import GoogleAdsCreateKeywordsOutput
from integrations.google_ads.tools.utils import edit_runs
from services.audit_events import AuditStatus
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.google_ads.support import _writable_google_ads_entry

_MANUAL = {"name": "Trail", "status": "ENABLED", "biddingStrategyType": "MANUAL_CPC"}
_SMART = {"name": "Waterproof", "status": "ENABLED", "biddingStrategyType": "MAXIMIZE_CONVERSIONS"}


def _ad_group_row(ad_group_id: str, name: str, campaign: dict[str, Any]) -> dict[str, Any]:
    return {
        "adGroup": {
            "resourceName": f"customers/111/adGroups/{ad_group_id}",
            "name": name,
            "status": "ENABLED",
            "type": "SEARCH_STANDARD",
            "cpcBidMicros": "850000",
        },
        "campaign": {**campaign, "advertisingChannelType": "SEARCH"},
    }


class _Account:
    """One Google Ads account: answers ad group and keyword reads, and records mutates."""

    def __init__(self, ad_groups: list[dict[str, Any]], keywords: list[tuple[str, str, str]]):
        self.ad_groups = ad_groups
        self.keywords = keywords
        self.mutates: list[dict[str, Any]] = []

    async def post(self, path: str, **kwargs: Any) -> Any:
        body = kwargs["json"]
        if path.endswith("googleAds:searchStream"):
            if "FROM ad_group_criterion" in body["query"]:
                rows = [
                    {
                        "adGroup": {"id": ad_group_id},
                        "adGroupCriterion": {
                            "resourceName": f"customers/111/adGroupCriteria/{ad_group_id}~9{at}",
                            "keyword": {"text": text, "matchType": match_type},
                        },
                    }
                    for at, (ad_group_id, text, match_type) in enumerate(self.keywords)
                ]
                return [{"results": rows}]
            return [{"results": self.ad_groups}]
        self.mutates.append(body)
        responses = []
        for operation in body["mutateOperations"]:
            created = operation["adGroupCriterionOperation"]["create"]
            ad_group_id = created["adGroup"].rsplit("/", 1)[-1]
            keyword = (ad_group_id, created["keyword"]["text"], created["keyword"]["matchType"])
            if not body["validateOnly"]:
                self.keywords.append(keyword)
            criterion = f"customers/111/adGroupCriteria/{ad_group_id}~9{len(self.keywords) - 1}"
            responses.append({"adGroupCriterionResult": {"resourceName": criterion}})
        return {"mutateOperationResponses": responses}


def _reference(ad_group_id: str, name: str, customer_id: str = "111") -> GoogleAdsAdGroupReference:
    return GoogleAdsAdGroupReference(
        customer_id=customer_id,
        campaign_id="10",
        ad_group_id=ad_group_id,
        label=name,
        scope_label="Trail",
    )


def _entry():
    entry = _writable_google_ads_entry()
    metadata = {**entry.permissions_metadata, "currency_code": "GBP", "time_zone": "Europe/London"}
    return replace(entry, permissions_metadata=metadata)


def _request(*entries: dict[str, Any], status: str = "PAUSED"):
    return tool_module.GoogleAdsCreateKeywordsRequest.model_validate(
        {"entries": list(entries), "status": status}
    )


async def _display(monkeypatch, account: _Account, request) -> dict[str, Any]:
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


async def _run(monkeypatch, account: _Account, request, display: dict[str, Any]):
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
        tool_name="google_ads_create_keywords",
        tool_call_id="create-keywords-call",
    )
    result = await tool_module.google_ads_create_keywords(ctx, request.entries, request.status)
    shown = GoogleAdsCreateKeywordsOutput.model_validate(result.metadata["public_result"])
    return shown.results[0].data, result.return_value["results"][0]["data"], audit


async def test_each_ad_group_gets_its_own_keywords_in_one_request(monkeypatch) -> None:
    account = _Account(
        [
            _ad_group_row("20", "Men's Trail", _MANUAL),
            _ad_group_row("21", "Women's Trail", _MANUAL),
        ],
        keywords=[],
    )
    request = _request(
        {
            "ad_group": _reference("20", "Men's Trail"),
            "keywords": [
                {"text": "mens  trail shoes", "match_type": "EXACT", "cpc_bid": "0.90"},
                {"text": "trail shoes for men", "match_type": "PHRASE"},
            ],
        },
        {
            "ad_group": _reference("21", "Women's Trail"),
            "keywords": [
                {
                    "text": "womens trail runners",
                    "match_type": "BROAD",
                    "final_url": "https://example.com/women",
                }
            ],
        },
    )
    display = await _display(monkeypatch, account, request)

    shown, told, audit = await _run(monkeypatch, account, request, display)

    assert display["_ad_groups"]["customers/111/adGroups/20"]["default_bid"] == "0.85"
    sent = account.mutates[-1]
    assert sent["validateOnly"] is False
    assert [op["adGroupCriterionOperation"]["create"] for op in sent["mutateOperations"]] == [
        {
            "adGroup": "customers/111/adGroups/20",
            "status": "PAUSED",
            "negative": False,
            "keyword": {"text": "mens trail shoes", "matchType": "EXACT"},
            "cpcBidMicros": "900000",
        },
        {
            "adGroup": "customers/111/adGroups/20",
            "status": "PAUSED",
            "negative": False,
            "keyword": {"text": "trail shoes for men", "matchType": "PHRASE"},
        },
        {
            "adGroup": "customers/111/adGroups/21",
            "status": "PAUSED",
            "negative": False,
            "keyword": {"text": "womens trail runners", "matchType": "BROAD"},
            "finalUrls": ["https://example.com/women"],
        },
    ]
    assert [(row.ad_group_name, row.outcome) for row in shown.keywords] == [
        ("Men's Trail", "added"),
        ("Men's Trail", "added"),
        ("Women's Trail", "added"),
    ]
    assert told["counts"]["added"] == 3 and told["keywords"] == []
    assert audit.await_args.kwargs["status"] == AuditStatus.SUCCESS


async def test_an_existing_keyword_and_an_ignored_bid_are_refused_before_any_request(
    monkeypatch,
) -> None:
    account = _Account(
        [_ad_group_row("20", "Men's Trail", _MANUAL), _ad_group_row("21", "Waterproof", _SMART)],
        keywords=[("20", "Mens Trail Shoes", "EXACT")],
    )
    request = _request(
        {
            "ad_group": _reference("20", "Men's Trail"),
            "keywords": [{"text": "mens trail shoes", "match_type": "EXACT"}],
        },
        {
            "ad_group": _reference("21", "Waterproof"),
            "keywords": [{"text": "waterproof trail shoes", "match_type": "EXACT", "cpc_bid": "1"}],
        },
    )

    display = await _display(monkeypatch, account, request)
    shown, told, _audit = await _run(monkeypatch, account, request, display)

    assert all(check["problem"] for check in display["_checks"].values())
    assert account.mutates == []
    assert [row.outcome for row in shown.keywords] == ["failed", "failed"]
    assert told["counts"]["failed"] == 2


async def test_a_keyword_edited_after_the_check_is_not_sent(monkeypatch) -> None:
    account = _Account([_ad_group_row("20", "Men's Trail", _MANUAL)], keywords=[])
    checked = _request(
        {
            "ad_group": _reference("20", "Men's Trail"),
            "keywords": [{"text": "mens trail shoes", "match_type": "EXACT", "cpc_bid": "0.50"}],
        }
    )
    display = await _display(monkeypatch, account, checked)
    edited = _request(
        {
            "ad_group": _reference("20", "Men's Trail"),
            "keywords": [{"text": "mens trail shoes", "match_type": "EXACT", "cpc_bid": "5.00"}],
        }
    )
    dry_runs = len(account.mutates)

    shown, _told, _audit = await _run(monkeypatch, account, edited, display)

    assert len(account.mutates) == dry_runs
    assert shown.keywords[0].outcome == "failed"
