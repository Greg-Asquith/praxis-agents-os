# apps/api/tests/integrations/google_ads/test_update_ads_tool.py

"""Editing responsive search ads: the merge checked before approval, one masked request after."""

from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

from integrations.google_ads.references import GoogleAdsAdReference
from integrations.google_ads.tools import update_ads as tool_module
from integrations.google_ads.tools.schemas.ad_updates import GoogleAdsUpdateAdsOutput
from integrations.google_ads.tools.utils import edit_runs
from services.audit_events import AuditStatus
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.google_ads.support import _writable_google_ads_entry

_AD_GROUP_AD = "customers/111/adGroupAds/20~30"
_AD = "customers/111/ads/30"


def _ad(*headlines: dict[str, str], **ad: Any) -> dict[str, Any]:
    return {
        "resourceName": _AD,
        "id": "30",
        "type": "RESPONSIVE_SEARCH_AD",
        "finalUrls": ["https://northwind.example/trail"],
        "responsiveSearchAd": {
            "headlines": list(headlines),
            "descriptions": [{"text": "Grippy trail shoes."}, {"text": "Next-day delivery."}],
            "path1": "trail",
        },
        **ad,
    }


class _Account:
    """One Google Ads account holding one ad: answers ad reads and applies `adOperation`s."""

    def __init__(self, ad: dict[str, Any]):
        self.ad = ad
        self.mutates: list[dict[str, Any]] = []

    async def post(self, path: str, **kwargs: Any) -> Any:
        body = kwargs["json"]
        if path.endswith("googleAds:searchStream"):
            row = {
                "adGroupAd": {
                    "resourceName": _AD_GROUP_AD,
                    "status": "ENABLED",
                    "ad": self.ad,
                    "policySummary": {
                        "reviewStatus": "REVIEW_IN_PROGRESS",
                        "approvalStatus": "UNKNOWN",
                    },
                },
                "adGroup": {"name": "Trail Shoes", "status": "ENABLED"},
                "campaign": {"name": "Running", "status": "ENABLED"},
            }
            return [{"results": [row]}]
        self.mutates.append(body)
        responses = []
        for operation in body["mutateOperations"]:
            update = operation["adOperation"]["update"]
            if not body["validateOnly"]:
                for field in operation["adOperation"]["updateMask"].split(","):
                    *parents, leaf = field.split(".")
                    source, target = update, self.ad
                    for part in parents:
                        source, target = source.get(part, {}), target.setdefault(part, {})
                    if leaf in source:
                        target[leaf] = source[leaf]
                    else:
                        target.pop(leaf, None)
            responses.append({"adResult": {"resourceName": update["resourceName"]}})
        return {"mutateOperationResponses": responses}


def _changes(**edits: Any) -> list[Any]:
    reference = GoogleAdsAdReference(
        customer_id="111", campaign_id="10", ad_group_id="20", ad_id="30", label="Trail ad"
    )
    return tool_module.GoogleAdsUpdateAdsRequest.model_validate(
        {"changes": [{"ad": reference, **edits}]}
    ).changes


def _entry():
    entry = _writable_google_ads_entry()
    metadata = {**entry.permissions_metadata, "currency_code": "GBP", "time_zone": "Europe/London"}
    return replace(entry, permissions_metadata=metadata)


def _deps() -> SimpleNamespace:
    return SimpleNamespace(
        db=None,
        user=None,
        workspace=None,
        active_context=ResolvedActiveContext(entries=(_entry(),)),
    )


async def _display(monkeypatch, account: _Account, changes: list[Any]) -> dict[str, Any]:
    monkeypatch.setattr(
        tool_module, "google_ads_client_for_principal", AsyncMock(return_value=account)
    )
    args = {"changes": [change.model_dump(mode="json") for change in changes]}
    return await tool_module._approval_display_args(_deps(), args)


async def _run(monkeypatch, account: _Account, changes: list[Any], display: dict[str, Any]):
    monkeypatch.setattr(edit_runs, "google_ads_client", AsyncMock(return_value=account))
    monkeypatch.setattr(tool_module, "approved_display_args", lambda _ctx: display)
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=_deps().active_context,
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name="google_ads_update_ads",
        tool_call_id="update-ads-call",
    )
    result = await tool_module.google_ads_update_ads(ctx, changes)
    return GoogleAdsUpdateAdsOutput.model_validate(result).results[0].data, audit


async def test_a_headline_swap_keeps_its_place_and_sends_only_what_changed(monkeypatch) -> None:
    account = _Account(
        _ad(
            {"text": "Trail Running Shoes", "pinnedField": "HEADLINE_1"},
            {"text": "Shop the Range"},
            {"text": "Next-Day Delivery"},
        )
    )
    changes = _changes(
        remove_headlines=["Shop the Range"],
        add_headlines=[{"text": "Free Returns on Every Order", "pin": "HEADLINE_2"}],
        pins=[{"text": "Trail Running Shoes", "pin": None}],
        path1="",
    )
    display = await _display(monkeypatch, account, changes)

    data, audit = await _run(monkeypatch, account, changes, display)

    headlines = [
        {"text": "Trail Running Shoes"},
        {"text": "Free Returns on Every Order", "pinnedField": "HEADLINE_2"},
        {"text": "Next-Day Delivery"},
    ]
    assert [body["validateOnly"] for body in account.mutates] == [True, False]
    assert account.mutates[-1]["mutateOperations"] == [
        {
            "adOperation": {
                # The cleared path is masked and left out of the body; descriptions don't change.
                "update": {"resourceName": _AD, "responsiveSearchAd": {"headlines": headlines}},
                "updateMask": "responsiveSearchAd.headlines,responsiveSearchAd.path1",
            }
        }
    ]
    [ad] = data.ads
    assert ad.outcome == "updated" and ad.review_status == "REVIEW_IN_PROGRESS"
    assert [item.text for item in ad.after.headlines] == [item["text"] for item in headlines]
    assert ad.before.path1 == "trail" and ad.after.path1 is None
    assert audit.await_args.kwargs["status"] == AuditStatus.SUCCESS


async def test_an_edit_leaving_too_many_headlines_is_refused_before_google_sees_it(
    monkeypatch,
) -> None:
    account = _Account(_ad(*({"text": f"Headline {number}"} for number in range(15))))
    changes = _changes(add_headlines=[{"text": "One More"}])

    display = await _display(monkeypatch, account, changes)
    data, _audit = await _run(monkeypatch, account, changes, display)

    assert display["_checks"][_AD_GROUP_AD]["problems"]
    assert account.mutates == []
    assert data.ads[0].outcome == "failed"
    # The result still says what was asked for, past what an ad can hold.
    assert len(data.ads[0].requested.headlines) == 16


async def test_an_edit_the_approval_check_did_not_cover_is_refused(monkeypatch) -> None:
    account = _Account(_ad({"text": "One"}, {"text": "Two"}, {"text": "Three"}))
    display = await _display(monkeypatch, account, _changes(path2="shoes"))
    edited = _changes(path2="shoes", final_url="https://elsewhere.example/")

    data, _audit = await _run(monkeypatch, account, edited, display)

    assert [body["validateOnly"] for body in account.mutates] == [True]
    assert data.ads[0].message == tool_module.NOT_SHOWN
    assert account.ad["finalUrls"] == ["https://northwind.example/trail"]
