# apps/api/tests/integrations/google_ads/test_optimise_search_terms_tool.py

"""Search terms: Google's figures and checks before approval, then one send per account."""

from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from integrations.google_ads.tools import optimise_search_terms as tool_module
from integrations.google_ads.tools.schemas.search_terms import (
    GoogleAdsOptimiseSearchTermsOutput,
    GoogleAdsOptimiseSearchTermsRequest,
)
from integrations.google_ads.tools.utils import edit_runs
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.google_ads.support import KeywordsAccount, _writable_google_ads_entry

_C = "customers/111"
_TRAIL_SHOES = {
    "customer_id": "111",
    "campaign_id": "10",
    "ad_group_id": "40",
    "label": "Trail Shoes",
    "scope_label": "Trail",
}
_WATERPROOF = {**_TRAIL_SHOES, "ad_group_id": "41", "label": "Waterproof Shoes"}


def _account() -> KeywordsAccount:
    account = KeywordsAccount()
    account.search_terms = [
        ("40", "running shoe jobs", "NONE", 12, 9_400_000, 0.0),
        ("40", "shoe repair near me", "NONE", 7, 5_150_000, 0.0),
        ("41", "waterproof fell shoes", "NONE", 38, 31_200_000, 6.0),
    ]
    return account


def _negative(term: str, level: str, match_type: str = "PHRASE", **extra: Any) -> dict[str, Any]:
    return {
        "search_term": term,
        "ad_group": _TRAIL_SHOES,
        "action": "add_negative",
        "match_type": match_type,
        "level": level,
        **extra,
    }


def _keyword(term: str, ad_group: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "search_term": term,
        "ad_group": ad_group,
        "action": "add_keyword",
        "match_type": "EXACT",
        **extra,
    }


def _args(*decisions: dict[str, Any]) -> dict[str, Any]:
    return GoogleAdsOptimiseSearchTermsRequest.model_validate(
        {"start_date": "2026-11-03", "end_date": "2026-11-09", "decisions": list(decisions)}
    ).model_dump(mode="json")


def _entry():
    entry = _writable_google_ads_entry()
    metadata = {**entry.permissions_metadata, "currency_code": "GBP", "time_zone": "Europe/London"}
    return replace(entry, permissions_metadata=metadata)


async def _display(monkeypatch, account: KeywordsAccount, args: dict[str, Any]) -> dict[str, Any]:
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


async def _run(monkeypatch, account: KeywordsAccount, args: dict[str, Any], display: dict):
    monkeypatch.setattr(edit_runs, "google_ads_client", AsyncMock(return_value=account))
    monkeypatch.setattr(tool_module, "approved_display_args", lambda _ctx: display)
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        AsyncMock(return_value=uuid4()),
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(_entry(),)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name="google_ads_optimise_search_terms",
        tool_call_id="optimise-search-terms-call",
    )
    request = GoogleAdsOptimiseSearchTermsRequest.model_validate(args)
    result = await tool_module.google_ads_optimise_search_terms(
        ctx, request.start_date, request.end_date, request.decisions
    )
    GoogleAdsOptimiseSearchTermsOutput.model_validate(result.return_value)
    shown = GoogleAdsOptimiseSearchTermsOutput.model_validate(result.metadata["public_result"])
    return shown.model_dump(mode="json")["results"][0]["data"]


def _outcomes(data: dict[str, Any]) -> dict[str, str]:
    return {row["search_term"]: row["outcome"] for row in data["outcomes"]}


async def test_one_approval_blocks_terms_at_two_levels_and_adds_a_keyword(monkeypatch) -> None:
    account = _account()
    args = _args(
        _negative("running shoe jobs", "campaign", "BROAD"),
        _negative("shoe repair near me", "ad_group"),
        _keyword("waterproof fell shoes", _WATERPROOF),
    )

    display = await _display(monkeypatch, account, args)
    checks = display["_checks"]
    assert all(check["problem"] is None for check in checks.values())
    # The card's figures are Google's, read for the request's dates.
    term = checks[f"{_C}/adGroups/41/add_keyword/waterproof fell shoes"]
    assert (term["clicks"], term["cost"], term["conversions"]) == (38, "31.2", 6.0)
    assert [body["validateOnly"] for body in account.mutates] == [True]

    data = await _run(monkeypatch, account, args, display)

    sent = account.mutates[-1]
    assert sent["partialFailure"] is True
    assert sent["mutateOperations"] == [
        {
            "campaignCriterionOperation": {
                "create": {
                    "campaign": f"{_C}/campaigns/10",
                    "negative": True,
                    "keyword": {"text": "running shoe jobs", "matchType": "BROAD"},
                }
            }
        },
        {
            "adGroupCriterionOperation": {
                "create": {
                    "adGroup": f"{_C}/adGroups/40",
                    "negative": True,
                    "keyword": {"text": "shoe repair near me", "matchType": "PHRASE"},
                }
            }
        },
        {
            "adGroupCriterionOperation": {
                "create": {
                    "adGroup": f"{_C}/adGroups/41",
                    "status": "ENABLED",
                    "negative": False,
                    "keyword": {"text": "waterproof fell shoes", "matchType": "EXACT"},
                }
            }
        },
    ]
    assert data["counts"] == {
        "negatives_added": 2,
        "keywords_added": 1,
        "already_set": 0,
        "failed": 0,
        "unverified": 0,
    }


async def test_a_term_already_excluded_is_already_set_and_sends_nothing(monkeypatch) -> None:
    account = _account()
    account.negatives[f"{_C}/campaignCriteria/10~5"] = (
        "campaigns",
        "10",
        "Running Shoe Jobs",
        "BROAD",
    )
    args = _args(_negative("running shoe jobs", "campaign", "BROAD"))

    display = await _display(monkeypatch, account, args)
    data = await _run(monkeypatch, account, args, display)

    assert account.mutates == []
    assert _outcomes(data) == {"running shoe jobs": "already_set"}


async def test_terms_missing_from_the_report_or_blocking_a_keyword_are_never_sent(
    monkeypatch,
) -> None:
    account = _account()
    account.search_terms.append(("40", "waterproof", "NONE", 3, 2_100_000, 0.0))
    args = _args(
        _negative("salomon speedcross", "ad_group"),
        # Would block the keyword the same request adds in Waterproof Shoes.
        _negative("waterproof", "campaign", "BROAD"),
        _keyword("waterproof fell shoes", _WATERPROOF),
    )

    display = await _display(monkeypatch, account, args)
    problems = {
        key.rsplit("/", 1)[1]: check["problem"] for key, check in display["_checks"].items()
    }
    assert problems == {
        "salomon speedcross": (
            "Not in the search terms report for 3 Nov 2026 to 9 Nov 2026 in Trail Shoes."
        ),
        "waterproof": (
            "Blocks “waterproof fell shoes”, which this request adds as a keyword in "
            "Waterproof Shoes."
        ),
        "waterproof fell shoes": None,
    }

    data = await _run(monkeypatch, account, args, display)

    sent = account.mutates[-1]["mutateOperations"]
    assert len(sent) == 1
    assert sent[0]["adGroupCriterionOperation"]["create"]["negative"] is False
    assert _outcomes(data) == {
        "salomon speedcross": "failed",
        "waterproof": "failed",
        "waterproof fell shoes": "added",
    }


async def test_a_decision_changed_on_the_card_is_not_sent_until_google_checked_it(
    monkeypatch,
) -> None:
    account = _account()
    proposed = _args(_negative("running shoe jobs", "ad_group"))
    # The approver saw an ad group negative; the request now blocks the whole campaign.
    edited = _args(_negative("running shoe jobs", "campaign"))
    display = await _display(monkeypatch, account, proposed)

    data = await _run(monkeypatch, account, edited, display)

    assert all(body["validateOnly"] for body in account.mutates)
    assert _outcomes(data) == {"running shoe jobs": "failed"}


def test_a_keyword_cannot_go_to_an_ad_group_in_another_account() -> None:
    elsewhere = {**_WATERPROOF, "customer_id": "222"}
    with pytest.raises(ValueError, match="only in the account it matched in"):
        _args(_keyword("waterproof fell shoes", _TRAIL_SHOES, keyword_ad_group=elsewhere))
