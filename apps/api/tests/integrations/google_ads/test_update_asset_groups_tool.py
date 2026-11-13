# apps/api/tests/integrations/google_ads/test_update_asset_groups_tool.py

"""Changing live asset groups: one atomic request, minimums on the card, approval kept to what was shown."""

from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

from core.exceptions.integration import IntegrationFailureDisposition, IntegrationValidationError
from integrations.google_ads.operations.asset_group_state import LiveAssetGroup, LiveGroupLink
from integrations.google_ads.references import GoogleAdsAssetGroupReference
from integrations.google_ads.tools import update_asset_groups as tool_module
from integrations.google_ads.tools.schemas.asset_group_updates import (
    GoogleAdsUpdateAssetGroupsOutput,
    GoogleAdsUpdateAssetGroupsRequest,
)
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.google_ads.support import _writable_google_ads_entry

_C = "customers/111"
_GROUP = f"{_C}/assetGroups/950"
_HEADLINES = {"501": "Rain Jackets", "502": "Stay Dry Outside", "503": "Built for the Hills"}


class _Account:
    """One Performance Max asset group: answers its reads and records mutates."""

    def __init__(
        self,
        *,
        headlines: dict[str, str] = _HEADLINES,
        audience_scope: str = "ASSET_GROUP",
        refuse: bool = False,
    ):
        self.headlines = headlines
        self.audience_scope = audience_scope
        # Google rejects the first request that would change the group.
        self.refuse = refuse
        self.mutates: list[dict[str, Any]] = []

    async def post(self, _path: str, **kwargs: Any) -> Any:
        body = kwargs["json"]
        if "query" in body:
            return [{"results": self._rows(body["query"])}]
        self.mutates.append(body)
        if self.refuse and not body["validateOnly"]:
            raise IntegrationValidationError(
                "Google Ads rejected the request.",
                provider_key="google_ads",
                failure_disposition=IntegrationFailureDisposition.REJECTED,
            )
        responses = []
        for index, operation in enumerate(body["mutateOperations"]):
            kind = next(iter(operation))
            resource = kind.removesuffix("Operation")
            change = operation[kind]
            name = change.get("remove") or (change.get("update") or {}).get("resourceName")
            name = (
                name
                or {
                    "asset": f"{_C}/assets/{600 + index}",
                    "assetGroupAsset": f"{_C}/assetGroupAssets/950~{600 + index}~HEADLINE",
                    "assetGroupSignal": f"{_C}/assetGroupSignals/950~{30 + index}",
                }[resource]
            )
            responses.append({f"{resource}Result": {"resourceName": name}})
        return {"mutateOperationResponses": responses}

    def _rows(self, query: str) -> list[dict[str, Any]]:
        group = {"assetGroup": {"id": "950"}}
        if "FROM asset_group_asset" in query:
            links = [(asset_id, "HEADLINE", text) for asset_id, text in self.headlines.items()] + [
                ("510", "LONG_HEADLINE", "Waterproof jackets for every trail")
            ]
            return [
                {
                    **group,
                    "assetGroupAsset": {
                        "resourceName": f"{_C}/assetGroupAssets/950~{asset_id}~{field_type}",
                        "fieldType": field_type,
                        "source": "ADVERTISER",
                    },
                    "asset": {"id": asset_id, "textAsset": {"text": text}},
                }
                for asset_id, field_type, text in links
            ]
        if "FROM asset_group_signal" in query:
            return [
                {
                    **group,
                    "assetGroupSignal": {
                        "resourceName": f"{_C}/assetGroupSignals/950~20",
                        "searchTheme": {"text": "rain jacket"},
                    },
                },
                {
                    **group,
                    "assetGroupSignal": {
                        "resourceName": f"{_C}/assetGroupSignals/950~21",
                        "audience": {"audience": f"{_C}/audiences/77"},
                    },
                },
            ]
        if "FROM audience " in query:
            return [
                {
                    "audience": {
                        "resourceName": f"{_C}/audiences/77",
                        "scope": self.audience_scope,
                        "dimensions": [
                            {"age": {"ageRanges": [{"minAge": 25}]}},
                            {
                                "audienceSegments": {
                                    "segments": [{"userList": {"userList": f"{_C}/userLists/401"}}]
                                }
                            },
                        ],
                    }
                }
            ]
        if "FROM asset_group " in query:
            return [
                {
                    "assetGroup": {
                        "id": "950",
                        "name": "Rain Jackets",
                        "status": "ENABLED",
                        "finalUrls": ["https://shop.test/rain"],
                        "trackingUrlTemplate": "{lpurl}?src=old",
                        "urlCustomParameters": [{"key": "season", "value": "winter"}],
                    },
                    "campaign": {
                        "name": "PMax Hiking UK",
                        "status": "ENABLED",
                        "advertisingChannelType": "PERFORMANCE_MAX",
                    },
                }
            ]
        if "FROM user_interest " in query and "80432" in query:
            return [{"userInterest": {"userInterestId": "80432", "name": "Hikers"}}]
        return []


def _args(**update: Any) -> dict[str, Any]:
    group = GoogleAdsAssetGroupReference(
        customer_id="111", campaign_id="10", asset_group_id="950", label="Rain Jackets"
    )
    return GoogleAdsUpdateAssetGroupsRequest.model_validate(
        {"entries": [{"asset_group": group.model_dump(mode="json"), **update}]}
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


async def _run(monkeypatch, account: _Account, args: dict[str, Any], display: dict[str, Any]):
    monkeypatch.setattr(tool_module, "google_ads_client", AsyncMock(return_value=account))
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
        tool_name="google_ads_update_asset_groups",
        tool_call_id="update-asset-groups-call",
    )
    request = GoogleAdsUpdateAssetGroupsRequest.model_validate(args)
    result = await tool_module.google_ads_update_asset_groups(ctx, request.entries)
    shown = result.metadata["public_result"]
    return GoogleAdsUpdateAssetGroupsOutput.model_validate(shown).results[0]


def _operations(body: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [(next(iter(op)), op[next(iter(op))]) for op in body["mutateOperations"]]


_SWAP = {
    "add_assets": {"headlines": ["Grip on Every Trail", "Free Returns"]},
    "remove_assets": {"headlines": ["Built for the Hills", "Stay Dry Outside"]},
}


async def test_a_swap_at_the_minimum_adds_first_then_removes_and_extends_the_signal(
    monkeypatch,
) -> None:
    account = _Account()
    args = _args(
        **_SWAP,
        add_search_themes=["waterproof hiking boots", "Rain Jacket"],
        add_audience_signals=[{"kind": "user_interest", "key": "80432"}],
    )
    display = await _display(monkeypatch, account, args)
    assert all(row["problem"] is None for row in display["_checks"][_GROUP]["rows"])
    account.mutates.clear()

    entry = await _run(monkeypatch, account, args, display)

    # Google checks the three-headline minimum as each request finds the group, so the new
    # headlines go in before the old ones come out.
    first, second = account.mutates
    assert first["validateOnly"] is False and first["partialFailure"] is False
    assert [kind for kind, _ in _operations(first)] == [
        "assetOperation",
        "assetOperation",
        "assetGroupAssetOperation",
        "assetGroupAssetOperation",
        "assetGroupSignalOperation",
        "audienceOperation",
    ]
    assert _operations(first)[2][1]["create"] == {
        "assetGroup": _GROUP,
        "asset": f"{_C}/assets/-1",
        "fieldType": "HEADLINE",
    }
    assert [body["remove"] for _kind, body in _operations(second)] == [
        f"{_C}/assetGroupAssets/950~503~HEADLINE",
        f"{_C}/assetGroupAssets/950~502~HEADLINE",
    ]
    # The audience keeps its age dimension and its list, and gains the interest.
    assert _operations(first)[5][1] == {
        "update": {
            "resourceName": f"{_C}/audiences/77",
            "dimensions": [
                {"age": {"ageRanges": [{"minAge": 25}]}},
                {
                    "audienceSegments": {
                        "segments": [
                            {"userList": {"userList": f"{_C}/userLists/401"}},
                            {"userInterest": {"userInterestCategory": f"{_C}/userInterests/80432"}},
                        ]
                    }
                },
            ],
        },
        "updateMask": "dimensions",
    }
    outcomes = {(row.kind, row.item, row.outcome) for row in entry.data.outcomes}
    assert ("HEADLINE", "Built for the Hills", "removed") in outcomes
    assert ("HEADLINE", "Grip on Every Trail", "added") in outcomes
    # A theme the group has, in another case, is reported without a change.
    assert ("search_theme", "Rain Jacket", "already_set") in outcomes


async def test_url_options_replace_and_clear_in_one_update_naming_only_what_changes(
    monkeypatch,
) -> None:
    account = _Account()
    args = _args(
        url_options={
            "final_url_suffix": "utm_source=google",
            "tracking_template": "",
            "custom_parameters": [{"key": "season", "value": "winter"}],
        }
    )
    display = await _display(monkeypatch, account, args)
    shown = [
        (row["row"], row["before"], row["state"]) for row in display["_checks"][_GROUP]["rows"]
    ]
    assert shown == [
        ("final_url_suffix", None, "change"),
        ("tracking_template", "{lpurl}?src=old", "change"),
        ("custom_parameters", "season=winter", "already_set"),
    ]
    account.mutates.clear()

    entry = await _run(monkeypatch, account, args, display)

    (sent,) = account.mutates
    # The parameters are live already, so the mask leaves them out; null clears the template.
    assert _operations(sent) == [
        (
            "assetGroupOperation",
            {
                "update": {
                    "resourceName": _GROUP,
                    "finalUrlSuffix": "utm_source=google",
                    "trackingUrlTemplate": None,
                },
                "updateMask": "finalUrlSuffix,trackingUrlTemplate",
            },
        )
    ]
    assert [(row.kind, row.outcome) for row in entry.data.outcomes] == [
        ("final_url_suffix", "changed"),
        ("tracking_template", "changed"),
        ("custom_parameters", "already_set"),
    ]


async def test_a_rejected_first_request_leaves_the_removals_unsent(monkeypatch) -> None:
    args = _args(**_SWAP)
    display = await _display(monkeypatch, _Account(), args)
    account = _Account(refuse=True)

    entry = await _run(monkeypatch, account, args, display)

    # The old headlines stay, so the group never drops under its minimum.
    assert len(account.mutates) == 1
    removals = [row for row in entry.data.outcomes if row.action == "remove"]
    assert {row.outcome for row in removals} == {"failed"}
    assert {row.error_code for row in removals} == {"NOT_SENT"}


async def test_the_card_refuses_a_removal_under_a_minimum_and_a_shared_audience(
    monkeypatch,
) -> None:
    account = _Account(audience_scope="CUSTOMER")
    args = _args(
        remove_assets={
            "headlines": ["Built for the Hills"],
            "long_headlines": ["Waterproof jackets for every trail"],
        },
        remove_audience_signals=[{"kind": "user_list", "key": "401"}],
    )

    rows = {
        row["row"]: row
        for row in (await _display(monkeypatch, account, args))["_checks"][_GROUP]["rows"]
    }

    assert rows["LONG_HEADLINE|Waterproof jackets for every trail"]["problem"] == (
        "Every asset group needs at least 1 long headline; this would leave 0."
    )
    # Three headlines leave two, under Google's three.
    assert (
        "at least 3 headlines; this would leave 2"
        in rows["HEADLINE|Built for the Hills"]["problem"]
    )
    assert "saved audience" in rows["audience_signal|user_list:401"]["problem"]
    # Nothing is left for Google to check, so no dry run is sent.
    assert account.mutates == []


async def test_a_change_live_differently_from_what_was_approved_is_refused_with_nothing_sent(
    monkeypatch,
) -> None:
    args = _args(add_assets={"headlines": ["Free Returns"]})
    display = await _display(monkeypatch, _Account(), args)
    # Someone added the same headline in Google Ads after approval.
    account = _Account(headlines={**_HEADLINES, "504": "Free Returns"})

    entry = await _run(monkeypatch, account, args, display)

    assert entry.status == "error" and "changed in Google Ads after" in entry.error_message
    assert account.mutates == []


async def test_a_removal_that_would_now_pass_a_minimum_is_refused_with_nothing_sent(
    monkeypatch,
) -> None:
    args = _args(remove_assets={"headlines": ["Built for the Hills"]})
    shown = _Account(headlines={**_HEADLINES, "504": "Free Returns"})
    display = await _display(monkeypatch, shown, args)
    # Someone removed another headline in Google Ads after approval, leaving the minimum.
    account = _Account()

    entry = await _run(monkeypatch, account, args, display)

    assert entry.status == "error" and "changed in Google Ads after" in entry.error_message
    assert account.mutates == []


def test_replacing_every_long_headline_never_passes_five_or_drops_under_one() -> None:
    live = [f"Old long headline {n}" for n in range(3)]
    group = LiveAssetGroup(
        resource_name=_GROUP,
        name="Rain Jackets",
        status="ENABLED",
        final_urls=(),
        campaign_name="PMax",
        channel="PERFORMANCE_MAX",
        campaign_status="ENABLED",
        retail=False,
        links=tuple(
            LiveGroupLink(f"{_GROUP}~{n}", str(n), "LONG_HEADLINE", text, text)
            for n, text in enumerate(live)
        ),
    )
    rows = [
        *(tool_module._Row(_GROUP, "remove", "LONG_HEADLINE", text, text) for text in live),
        *(
            tool_module._Row(_GROUP, "add", "LONG_HEADLINE", f"New long headline {n}", "")
            for n in range(3)
        ),
    ]

    parts = tool_module._parts(group, rows)

    count = 3
    for part in sorted(set(parts.values())):
        moved = [row for row in rows if parts[row.source] == part]
        removed = sum(row.action == "remove" for row in moved)
        added = len(moved) - removed
        # Each request is safe whether Google counts removals or additions first.
        assert count - removed >= 1 and count + added <= 5
        count += added - removed
    assert count == 3
