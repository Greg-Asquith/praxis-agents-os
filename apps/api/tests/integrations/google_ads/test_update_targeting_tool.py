# apps/api/tests/integrations/google_ads/test_update_targeting_tool.py

"""Changing Google Ads locations and languages: checks before approval, one request, read-back."""

import re
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry

from integrations.google_ads.entity_resolvers.targeting import search_location_options
from integrations.google_ads.tools import (
    search_targeting as search_module,
    update_targeting as tool_module,
)
from integrations.google_ads.tools.schemas.targeting import (
    GoogleAdsTargetingSearchOutput,
    GoogleAdsUpdateTargetingOutput,
    GoogleAdsUpdateTargetingRequest,
)
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.google_ads.support import _writable_google_ads_entry

_CAMPAIGN = "customers/111/campaigns/10"
_LOCATIONS = {"2826": "United Kingdom", "1006": "Manchester", "1007": "Leeds", "2000": "Wales"}
_LANGUAGES = {"1000": "English", "1039": "Welsh"}


def _location(key: str, *, negative: bool = False, modifier: float | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "resourceName": f"{_C_CRITERIA}10~{key}",
        "criterionId": key,
        "type": "LOCATION",
        "negative": negative,
        "location": {"geoTargetConstant": f"geoTargetConstants/{key}"},
    }
    return {**row, "bidModifier": modifier} if modifier else row


_C_CRITERIA = "customers/111/campaignCriteria/"


def _language(key: str) -> dict[str, Any]:
    return {
        "resourceName": f"{_C_CRITERIA}10~{key}",
        "criterionId": key,
        "type": "LANGUAGE",
        "negative": False,
        "language": {"languageConstant": f"languageConstants/{key}"},
    }


class _Account:
    """One Google Ads account: answers targeting reads and applies `googleAds:mutate` requests."""

    def __init__(
        self,
        criteria: list[dict[str, Any]],
        *,
        channel: str = "DISPLAY",
        rejected: dict[str, str] | None = None,
        status: str = "ENABLED",
    ) -> None:
        self.criteria = criteria
        self.channel = channel
        self.rejected = rejected or {}
        self.status = status
        self.setting = "PRESENCE_OR_INTEREST"
        self.mutates: list[dict[str, Any]] = []
        self.next_id = 500

    async def post(self, path: str, **kwargs: Any) -> Any:
        body = kwargs["json"]
        if path.endswith("googleAds:searchStream"):
            return [{"results": self._search(body["query"])}]
        assert path == "customers/111/googleAds:mutate"
        self.mutates.append(body)
        return self._mutate(body)

    def _search(self, query: str) -> list[dict[str, Any]]:
        if "FROM geo_target_constant" in query:
            ids = re.search(r"IN \(([^)]*)\)", query).group(1).split(", ")
            return [
                {"geoTargetConstant": {"id": key, "name": _LOCATIONS[key]}}
                for key in ids
                if key in _LOCATIONS
            ]
        if "FROM language_constant" in query:
            return [
                {"languageConstant": {"id": key, "name": name}} for key, name in _LANGUAGES.items()
            ]
        if "FROM campaign_criterion" in query:
            return [{"campaign": {"id": "10"}, "campaignCriterion": row} for row in self.criteria]
        return [
            {
                "campaign": {
                    "id": "10",
                    "name": "Trail",
                    "status": self.status,
                    "advertisingChannelType": self.channel,
                    "geoTargetTypeSetting": {"positiveGeoTargetType": self.setting},
                }
            }
        ]

    def _mutate(self, body: dict[str, Any]) -> dict[str, Any]:
        responses: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for index, operation in enumerate(body["mutateOperations"]):
            ((key, value),) = operation.items()
            label = str(value.get("create", value.get("remove", value.get("update"))))
            problem = next((m for text, m in self.rejected.items() if text in label), None)
            if problem:
                responses.append({})
                errors.append(
                    {
                        "message": problem,
                        "errorCode": {"criterionError": "INVALID"},
                        "location": {
                            "fieldPathElements": [
                                {"fieldName": "mutate_operations", "index": index}
                            ]
                        },
                    }
                )
                continue
            name = self._apply(value, apply=not body["validateOnly"])
            responses.append({key.replace("Operation", "Result"): {"resourceName": name}})
        reply: dict[str, Any] = {"mutateOperationResponses": responses}
        if errors:
            reply["partialFailureError"] = {"details": [{"errors": errors}]}
        return reply

    def _apply(self, value: dict[str, Any], *, apply: bool) -> str:
        if "remove" in value:
            if apply:
                self.criteria = [r for r in self.criteria if r["resourceName"] != value["remove"]]
            return value["remove"]
        if "update" in value:
            update = value["update"]
            if apply and "geoTargetTypeSetting" in update:
                self.setting = update["geoTargetTypeSetting"]["positiveGeoTargetType"]
            for row in self.criteria if apply else ():
                if row["resourceName"] == update["resourceName"]:
                    row["bidModifier"] = update["bidModifier"]
            return update["resourceName"]
        self.next_id += 1
        name = f"{_C_CRITERIA}10~{self.next_id}"
        if apply:
            create = value["create"]
            kind = (
                "LOCATION"
                if "location" in create
                else "PROXIMITY"
                if "proximity" in create
                else "LANGUAGE"
            )
            self.criteria.append(
                {
                    "resourceName": name,
                    "criterionId": str(self.next_id),
                    "type": kind,
                    **{key: item for key, item in create.items() if key != "campaign"},
                }
            )
        return name


def _campaign() -> dict[str, Any]:
    return {"customer_id": "111", "campaign_id": "10", "label": "Trail"}


def _args(**change: Any) -> dict[str, Any]:
    return GoogleAdsUpdateTargetingRequest.model_validate(
        {"changes": [{"campaign": _campaign(), **change}]}
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
        tool_name="google_ads_update_targeting",
        tool_call_id="update-targeting-call",
    )
    changes = GoogleAdsUpdateTargetingRequest.model_validate(args).changes
    result = await tool_module.google_ads_update_targeting(ctx, changes)
    return GoogleAdsUpdateTargetingOutput.model_validate(result).model_dump(mode="json"), audit


def _rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    return result["results"][0]["data"]["outcomes"]


def _check(display: dict[str, Any]) -> dict[str, Any]:
    return display["_checks"]["campaigns"][_CAMPAIGN]


async def test_one_approval_adds_cities_moves_a_region_to_excluded_and_removes_a_language(
    monkeypatch,
) -> None:
    account = _Account([_location("2826"), _location("2000"), _language("1000"), _language("1039")])
    args = _args(
        add_locations=[
            {"key": "1006", "name": "Manchester", "bid_adjustment": 15},
            {"key": "1007", "name": "Leeds"},
        ],
        exclude_locations=[{"key": "2000", "name": "Wales"}],
        remove_languages=[{"key": "1039", "name": "Welsh"}],
    )

    display = await _display(monkeypatch, account, args)
    assert _check(display)["problem"] is None
    assert _check(display)["item_problems"] == []
    assert account.mutates[-1]["validateOnly"] is True

    result, audit = await _run(monkeypatch, account, args, display)

    sent = account.mutates[-1]
    assert sent["validateOnly"] is False and sent["partialFailure"] is True
    assert sent["mutateOperations"] == [
        {"campaignCriterionOperation": {"remove": f"{_C_CRITERIA}10~2000"}},
        {"campaignCriterionOperation": {"remove": f"{_C_CRITERIA}10~1039"}},
        {
            "campaignCriterionOperation": {
                "create": {
                    "campaign": _CAMPAIGN,
                    "negative": True,
                    "location": {"geoTargetConstant": "geoTargetConstants/2000"},
                }
            }
        },
        {
            "campaignCriterionOperation": {
                "create": {
                    "campaign": _CAMPAIGN,
                    "location": {"geoTargetConstant": "geoTargetConstants/1006"},
                    "bidModifier": 1.15,
                }
            }
        },
        {
            "campaignCriterionOperation": {
                "create": {
                    "campaign": _CAMPAIGN,
                    "location": {"geoTargetConstant": "geoTargetConstants/1007"},
                }
            }
        },
    ]
    assert {
        (row["setting"], row["action"], row["outcome"], row["count"]) for row in _rows(result)
    } == {
        ("locations", "remove", "updated", 1),
        ("excluded_locations", "add", "updated", 1),
        ("languages", "remove", "updated", 1),
        ("locations", "add", "updated", 2),
    }
    detail = audit.await_args.kwargs["operation_detail"]
    assert "Manchester" not in str(detail)


async def test_a_radius_and_a_bid_change_send_exact_values_and_an_equal_bid_is_already_set(
    monkeypatch,
) -> None:
    account = _Account([_location("2826", modifier=1.2), _location("1006", modifier=1.1)])
    args = _args(
        add_locations=[
            {"key": "2826", "bid_adjustment": 20},
            {"key": "1006", "bid_adjustment": -30},
        ],
        add_radius=[{"latitude": 51.5, "longitude": -0.12, "radius": 10, "units": "MILES"}],
        location_setting="PRESENCE",
    )

    display = await _display(monkeypatch, account, args)
    result, _audit = await _run(monkeypatch, account, args, display)

    assert account.mutates[-1]["mutateOperations"] == [
        {
            "campaignCriterionOperation": {
                "update": {"resourceName": f"{_C_CRITERIA}10~1006", "bidModifier": 0.7},
                "updateMask": "bidModifier",
            }
        },
        {
            "campaignCriterionOperation": {
                "create": {
                    "campaign": _CAMPAIGN,
                    "proximity": {
                        "geoPoint": {
                            "latitudeInMicroDegrees": 51_500_000,
                            "longitudeInMicroDegrees": -120_000,
                        },
                        "radius": 10.0,
                        "radiusUnits": "MILES",
                    },
                }
            }
        },
        {
            "campaignOperation": {
                "update": {
                    "resourceName": _CAMPAIGN,
                    "geoTargetTypeSetting": {"positiveGeoTargetType": "PRESENCE"},
                },
                "updateMask": "geoTargetTypeSetting.positiveGeoTargetType",
            }
        },
    ]
    outcomes = {(row["setting"], row["action"], row["outcome"]) for row in _rows(result)}
    assert ("locations", "change_bid", "already_set") in outcomes
    assert ("locations", "change_bid", "updated") in outcomes
    # The read-back finds the radius it sent, so the add isn't reported as unconfirmed.
    assert ("radius", "add", "updated") in outcomes
    changed = next(
        row
        for row in _rows(result)
        if row["outcome"] == "updated" and row["action"] == "change_bid"
    )
    assert changed["items"][0]["previous_bid_adjustment"] == 10


async def test_a_search_campaign_can_remove_a_language_but_not_add_one(monkeypatch) -> None:
    account = _Account([_location("2826"), _language("1039")], channel="SEARCH")
    args = _args(
        add_languages=[{"key": "1000", "name": "English"}],
        remove_languages=[{"key": "1039", "name": "Welsh"}],
    )

    display = await _display(monkeypatch, account, args)

    assert [item["field"] for item in _check(display)["item_problems"]] == ["add_languages"]
    # Only the removal reaches Google's dry run.
    assert account.mutates[-1]["mutateOperations"] == [
        {"campaignCriterionOperation": {"remove": f"{_C_CRITERIA}10~1039"}}
    ]

    result, _audit = await _run(monkeypatch, account, args, display)

    assert {(row["action"], row["outcome"]) for row in _rows(result)} == {
        ("add", "failed"),
        ("remove", "updated"),
    }
    assert "language" not in str(account.mutates[-1]["mutateOperations"][1:])


async def test_leaving_a_campaign_with_no_location_is_refused_on_the_card_and_after_approval(
    monkeypatch,
) -> None:
    account = _Account([_location("2826")])
    args = _args(exclude_locations=[{"key": "2826"}])

    display = await _display(monkeypatch, account, args)

    assert "no location" in _check(display)["problem"]
    assert account.mutates == []

    result, _audit = await _run(monkeypatch, account, args, display)

    assert account.mutates == []
    assert {row["outcome"] for row in _rows(result)} == {"failed"}


async def test_an_add_that_cant_be_sent_doesnt_count_as_the_location_left(monkeypatch) -> None:
    account = _Account([_location("2826")], rejected={"geoTargetConstants/1006": "Not allowed."})
    for added in ("1006", "999999"):
        args = _args(remove_locations=[{"key": "2826"}], add_locations=[{"key": added}])

        display = await _display(monkeypatch, account, args)
        assert "no location" in _check(display)["problem"]
        account.mutates.clear()

        result, _audit = await _run(monkeypatch, account, args, display)

        assert account.mutates == []
        assert {row["outcome"] for row in _rows(result)} == {"failed"}


async def test_a_location_removed_after_the_check_stops_the_last_location_removal(
    monkeypatch,
) -> None:
    account = _Account([_location("2826"), _location("1006")])
    args = _args(remove_locations=[{"key": "1006"}])
    display = await _display(monkeypatch, account, args)
    assert _check(display)["problem"] is None
    account.mutates.clear()

    # Someone removes the only other location between the check and the send.
    account.criteria = [_location("1006")]
    result, _audit = await _run(monkeypatch, account, args, display)

    assert account.mutates == []
    assert {row["outcome"] for row in _rows(result)} == {"failed"}


async def test_a_criterion_changed_since_approval_is_refused_and_the_rest_are_sent(
    monkeypatch,
) -> None:
    account = _Account([_location("2826"), _location("1006")])
    args = _args(
        remove_locations=[{"key": "1006"}],
        add_locations=[{"key": "1007"}],
    )
    display = await _display(monkeypatch, account, args)

    account.criteria = [_location("2826")]
    result, _audit = await _run(monkeypatch, account, args, display)

    by_action = {row["action"]: row for row in _rows(result)}
    assert by_action["remove"]["error_code"] == "CHANGED_SINCE_APPROVAL"
    assert by_action["add"]["outcome"] == "updated"


async def test_a_campaign_google_couldnt_check_is_never_sent(monkeypatch) -> None:
    account = _Account([_location("2826")])
    args = _args(add_locations=[{"key": "1006"}])
    display = {"_checks": {"campaigns": {_CAMPAIGN: {"unavailable": True}}, "names": {}}}

    result, _audit = await _run(monkeypatch, account, args, display)

    assert account.mutates == []
    assert {row["outcome"] for row in _rows(result)} == {"failed"}


async def test_googles_rejection_names_its_item_and_an_unknown_key_never_reaches_google(
    monkeypatch,
) -> None:
    account = _Account([_location("2826")], rejected={"geoTargetConstants/1006": "Not allowed."})
    args = _args(add_locations=[{"key": "1006"}, {"key": "999999"}])

    display = await _display(monkeypatch, account, args)

    problems = {item["key"]: item["message"] for item in _check(display)["item_problems"]}
    assert problems == {
        "1006": "Google says: Not allowed.",
        "999999": "Google Ads doesn't recognise this location.",
    }
    assert "999999" not in str(account.mutates[-1])


async def test_a_campaign_from_another_account_is_refused(monkeypatch) -> None:
    account = _Account([_location("2826")])
    args = _args(add_locations=[{"key": "1006"}])
    args["changes"][0]["campaign"]["customer_id"] = "222"

    with pytest.raises(ModelRetry):
        await _run(monkeypatch, account, args, {"_checks": {}})

    assert account.mutates == []


class _SuggestClient:
    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []

    async def post(self, path: str, **kwargs: Any) -> Any:
        assert path == "geoTargetConstants:suggest"
        self.bodies.append(kwargs["json"])
        return {
            "geoTargetConstantSuggestions": [
                {
                    "searchTerm": "Manchester",
                    "reach": "2900000",
                    "geoTargetConstant": {
                        "resourceName": "geoTargetConstants/1006",
                        "id": "1006",
                        "name": "Manchester",
                        "countryCode": "GB",
                        "targetType": "City",
                        "canonicalName": "Manchester,England,United Kingdom",
                    },
                },
                {
                    "searchTerm": "Manchester",
                    "geoTargetConstant": {
                        "id": "1014",
                        "name": "Manchester",
                        "countryCode": "US",
                        "targetType": "City",
                        "canonicalName": "Manchester,New Hampshire,United States",
                    },
                },
                {
                    "searchTerm": "Leeds",
                    "geoTargetConstant": {"id": "1007", "name": "Leeds", "targetType": "City"},
                },
            ]
        }


async def test_search_returns_keys_regions_and_reach_for_every_name(monkeypatch) -> None:
    client = _SuggestClient()
    monkeypatch.setattr(search_module, "google_ads_client", AsyncMock(return_value=client))
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
        tool_name="google_ads_search_targeting",
        tool_call_id="search-call",
    )

    result = await search_module.google_ads_search_targeting(
        ctx, "location", ["Manchester", "Leeds"], country_code="GB", limit=2
    )

    assert client.bodies == [
        {"locale": "en", "locationNames": {"names": ["Manchester", "Leeds"]}, "countryCode": "GB"}
    ]
    data = GoogleAdsTargetingSearchOutput.model_validate(result).results[0].data
    assert data.truncated is True
    assert (data.options[0].key, data.options[0].region, data.options[0].reach) == (
        "1006",
        "England, United Kingdom",
        2_900_000,
    )


async def test_a_pasted_list_finds_only_the_best_match_per_line(monkeypatch) -> None:
    client = _SuggestClient()
    monkeypatch.setattr(
        "integrations.google_ads.entity_resolvers.targeting.google_ads_client_for_principal",
        AsyncMock(return_value=client),
    )
    ctx = SimpleNamespace(
        db=None,
        actor=None,
        workspace=None,
        active_context=ResolvedActiveContext(entries=(_entry(),)),
    )

    pasted = await search_location_options(ctx, "Manchester\nLeeds\n", {}, 50, None)
    single = await search_location_options(ctx, "Manchester", {}, 50, None)

    assert [choice.value["key"] for choice in pasted.choices] == ["1006", "1007"]
    assert client.bodies[0]["locationNames"]["names"] == ["Manchester", "Leeds"]
    # One name lists every match, so the operator can choose between places with the same name.
    assert [choice.value["key"] for choice in single.choices] == ["1006", "1014", "1007"]
