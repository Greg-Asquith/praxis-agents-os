# apps/api/tests/integrations/google_ads/test_update_keywords_tool.py

"""Changing keyword bids, URLs, and match types: checks before approval, atomic swaps, read-back."""

import re
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry

from integrations.google_ads.references import GoogleAdsKeywordReference
from integrations.google_ads.tools import update_keywords as tool_module
from integrations.google_ads.tools.schemas.keyword_updates import GoogleAdsUpdateKeywordsOutput
from integrations.google_ads.tools.utils import edit_runs
from services.audit_events import AuditStatus
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.google_ads.support import _writable_google_ads_entry

_MANUAL = {"name": "Trail", "status": "ENABLED", "biddingStrategyType": "MANUAL_CPC"}
_SMART = {
    "name": "Waterproof",
    "status": "ENABLED",
    "biddingStrategyType": "MAXIMIZE_CONVERSIONS",
}
_AD_GROUP = "customers/111/adGroups/20"


def _name(criterion_id: str) -> str:
    return f"customers/111/adGroupCriteria/20~{criterion_id}"


def _keyword(
    criterion_id: str, text: str, match_type: str, campaign: dict[str, Any], **values: Any
) -> dict[str, Any]:
    return {
        "adGroupCriterion": {
            "resourceName": _name(criterion_id),
            "status": "ENABLED",
            "type": "KEYWORD",
            "negative": False,
            "keyword": {"text": text, "matchType": match_type},
            "cpcBidMicros": "500000",
            **values,
        },
        "adGroup": {"resourceName": _AD_GROUP, "id": "20", "name": "Shoes", "status": "ENABLED"},
        "campaign": dict(campaign),
    }


class _Account:
    """One Google Ads account: answers keyword reads and applies `googleAds:mutate` requests."""

    def __init__(self, *rows: dict[str, Any]):
        self.rows = {row["adGroupCriterion"]["resourceName"]: row for row in rows}
        self.mutates: list[dict[str, Any]] = []

    async def post(self, path: str, **kwargs: Any) -> Any:
        body = kwargs["json"]
        if path.endswith("googleAds:searchStream"):
            names = re.findall(r"'(customers/[^']+)'", body["query"])
            if names:
                return [{"results": [self.rows[name] for name in names if name in self.rows]}]
            # The ad group read finds every keyword the account bids on there.
            return [{"results": list(self.rows.values())}]
        self.mutates.append(body)
        responses = []
        for operation in body["mutateOperations"]:
            change = operation["adGroupCriterionOperation"]
            if "create" in change:
                name = _name(str(90 + len(self.rows)))
                created = change["create"]
                if not body["validateOnly"]:
                    row = _keyword("0", "", "", _MANUAL)
                    row["adGroupCriterion"] = {
                        "resourceName": name,
                        "type": "KEYWORD",
                        **{key: value for key, value in created.items() if key != "adGroup"},
                    }
                    self.rows[name] = row
            else:
                update = change["update"]
                name = update["resourceName"]
                if not body["validateOnly"]:
                    live = self.rows[name]["adGroupCriterion"]
                    for field in change["updateMask"].split(","):
                        if field in update:
                            live[field] = update[field]
                        else:
                            live.pop(field, None)
            responses.append({"adGroupCriterionResult": {"resourceName": name}})
        return {"mutateOperationResponses": responses}


def _changes(*entries: dict[str, Any]) -> list[Any]:
    return tool_module.GoogleAdsUpdateKeywordsRequest.model_validate(
        {
            "changes": [
                {
                    **{key: value for key, value in entry.items() if key != "customer_id"},
                    "keyword": GoogleAdsKeywordReference(
                        customer_id=entry.get("customer_id", "111"),
                        campaign_id="10",
                        ad_group_id="20",
                        criterion_id=entry["keyword"],
                        text="trail shoes",
                        match_type="BROAD",
                        status="ENABLED",
                        label="trail shoes",
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
        tool_name="google_ads_update_keywords",
        tool_call_id="update-keywords-call",
    )
    result = await tool_module.google_ads_update_keywords(ctx, changes)
    shown = GoogleAdsUpdateKeywordsOutput.model_validate(result.metadata["public_result"])
    return shown.results[0].data, result.return_value["results"][0]["data"], audit


async def test_bids_and_urls_change_in_place_with_one_masked_request(monkeypatch) -> None:
    account = _Account(
        _keyword("40", "trail shoes", "BROAD", _MANUAL, finalUrls=["https://example.com/a"]),
        _keyword("41", "fell shoes", "EXACT", _MANUAL),
    )
    changes = _changes(
        {"keyword": "40", "cpc_bid": "none", "final_urls": []},
        # The live match type, so nothing is replaced.
        {"keyword": "41", "cpc_bid": "0.75", "match_type": "EXACT"},
    )
    display = await _display(monkeypatch, account, changes)

    shown, told, audit = await _run(monkeypatch, account, changes, display)

    sent = account.mutates[-1]
    assert sent["validateOnly"] is False and sent["partialFailure"] is True
    assert sent["mutateOperations"] == [
        {
            "adGroupCriterionOperation": {
                # Masked and absent, which clears the keyword's own bid and URLs.
                "update": {"resourceName": _name("40"), "finalUrls": []},
                "updateMask": "cpcBidMicros,finalUrls",
            }
        },
        {
            "adGroupCriterionOperation": {
                "update": {"resourceName": _name("41"), "cpcBidMicros": "750000"},
                "updateMask": "cpcBidMicros",
            }
        },
    ]
    cleared, raised = shown.keywords
    assert [(row.setting, row.before, row.after) for row in cleared.settings] == [
        ("cpc_bid", "0.5", None),
        ("final_urls", ["https://example.com/a"], []),
    ]
    assert [(row.setting, row.outcome) for row in raised.settings] == [
        ("match_type", "already_set"),
        ("cpc_bid", "updated"),
    ]
    assert told["counts"]["updated"] == 2 and told["keywords"] == []
    assert audit.await_args.kwargs["status"] == AuditStatus.SUCCESS


async def test_a_new_match_type_pauses_and_adds_the_keyword_in_one_atomic_request(
    monkeypatch,
) -> None:
    account = _Account(
        _keyword("40", "trail shoes", "BROAD", _MANUAL, finalUrlSuffix="src=ads"),
    )
    changes = _changes({"keyword": "40", "match_type": "PHRASE", "cpc_bid": "0.90"})
    display = await _display(monkeypatch, account, changes)

    shown, _told, audit = await _run(monkeypatch, account, changes, display)

    sent = account.mutates[-1]
    assert sent["validateOnly"] is False and sent["partialFailure"] is False
    assert sent["mutateOperations"] == [
        {
            "adGroupCriterionOperation": {
                "update": {"resourceName": _name("40"), "status": "PAUSED"},
                "updateMask": "status",
            }
        },
        {
            "adGroupCriterionOperation": {
                "create": {
                    "adGroup": _AD_GROUP,
                    "status": "ENABLED",
                    "negative": False,
                    "keyword": {"text": "trail shoes", "matchType": "PHRASE"},
                    # The requested bid, with the old keyword's URL suffix carried over.
                    "cpcBidMicros": "900000",
                    "finalUrlSuffix": "src=ads",
                }
            },
        },
    ]
    (keyword,) = shown.keywords
    assert keyword.outcome == "updated"
    assert keyword.replacement in account.rows
    assert [(row.setting, row.after) for row in keyword.settings] == [
        ("match_type", "PHRASE"),
        ("cpc_bid", "0.9"),
    ]
    assert account.rows[_name("40")]["adGroupCriterion"]["status"] == "PAUSED"
    assert audit.await_args.kwargs["status"] == AuditStatus.SUCCESS


async def test_an_ignored_bid_and_an_existing_match_type_are_refused_before_any_request(
    monkeypatch,
) -> None:
    account = _Account(
        _keyword("40", "trail shoes", "BROAD", _SMART),
        _keyword("41", "trail shoes", "PHRASE", _SMART),
    )
    changes = _changes(
        {"keyword": "40", "match_type": "PHRASE"}, {"keyword": "41", "cpc_bid": "1.10"}
    )

    display = await _display(monkeypatch, account, changes)
    shown, told, _audit = await _run(monkeypatch, account, changes, display)

    checks = display["_checks"]
    assert set(checks[_name("40")]["problems"]) == {"match_type"}
    assert set(checks[_name("41")]["problems"]) == {"cpc_bid"}
    assert account.mutates == []
    assert [keyword.outcome for keyword in shown.keywords] == ["failed", "failed"]
    assert told["counts"]["failed"] == 2 and len(told["keywords"]) == 2


async def test_two_keywords_changed_to_the_same_match_type_keep_only_the_first(
    monkeypatch,
) -> None:
    account = _Account(
        _keyword("40", "trail shoes", "BROAD", _MANUAL),
        _keyword("41", "trail shoes", "EXACT", _MANUAL),
    )
    changes = _changes(
        {"keyword": "40", "match_type": "PHRASE"}, {"keyword": "41", "match_type": "PHRASE"}
    )

    display = await _display(monkeypatch, account, changes)
    shown, _told, _audit = await _run(monkeypatch, account, changes, display)

    assert set(display["_checks"][_name("41")]["problems"]) == {"match_type"}
    assert [keyword.outcome for keyword in shown.keywords] == ["updated", "failed"]
    assert account.rows[_name("41")]["adGroupCriterion"]["status"] == "ENABLED"


async def test_a_keyword_in_an_account_outside_the_context_is_refused(monkeypatch) -> None:
    account = _Account(_keyword("40", "trail shoes", "BROAD", _MANUAL))
    changes = _changes({"keyword": "40", "customer_id": "222", "cpc_bid": "0.50"})

    with pytest.raises(ModelRetry, match="no longer in the active integration context"):
        await _run(monkeypatch, account, changes, {"_checks": {}})

    assert account.mutates == []
