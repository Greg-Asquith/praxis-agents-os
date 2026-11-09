# apps/api/tests/integrations/google_ads/test_edit_and_build_seams.py

"""The Google Ads edit and build seams that every task-shaped write tool reuses."""

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from core.exceptions.integration import (
    IntegrationFailureDisposition,
    IntegrationTimeoutError,
    IntegrationValidationError,
)
from integrations.google_ads.operations.build import CampaignBuild, dry_run_build, send_build
from integrations.google_ads.operations.edits import (
    STALE_CODE,
    CriterionChange,
    Edit,
    FieldChange,
    apply_edits,
    prepare_edits,
)

_CAMPAIGN = "customers/333/campaigns/10"
_AD_GROUP = "customers/333/adGroups/20"


class _MutateClient:
    """Answers googleAds:mutate requests in order and records each request body."""

    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.bodies: list[dict[str, Any]] = []

    async def post(self, path: str, **kwargs: Any) -> Any:
        assert path == "customers/333/googleAds:mutate"
        self.bodies.append(kwargs["json"])
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class _LiveState:
    """Serves live values per edit key, changed between reads to model the account."""

    def __init__(self, *states: Mapping[str, Mapping[str, Any]]) -> None:
        self.states = list(states)

    async def __call__(self, edits: Sequence[Edit]) -> Mapping[str, Mapping[str, Any]]:
        state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return {edit.key: state[edit.key] for edit in edits if edit.key in state}


def _partial_failure(index: int, message: str) -> dict[str, Any]:
    return {
        "details": [
            {
                "errors": [
                    {
                        "message": message,
                        "errorCode": {"campaignError": "CANNOT_MODIFY_REMOVED_CAMPAIGN"},
                        "location": {
                            "fieldPathElements": [
                                {"fieldName": "mutate_operations", "index": index}
                            ]
                        },
                    }
                ]
            }
        ]
    }


async def _prepared(client: _MutateClient, read: _LiveState, edits: Sequence[Edit]) -> list[Edit]:
    return await prepare_edits(
        client,
        customer_id="333",
        login_customer_id="111",
        edits=edits,
        read=read,
        operation="update_status",
    )


async def _applied(client: _MutateClient, read: _LiveState, edits: Sequence[Edit]):
    return await apply_edits(
        client,
        customer_id="333",
        login_customer_id="111",
        edits=edits,
        read=read,
        family="status",
        operation="update_status",
    )


async def test_edit_refuses_an_object_changed_since_approval() -> None:
    read = _LiveState(
        {_CAMPAIGN: {"status": "ENABLED"}, _AD_GROUP: {"status": "ENABLED"}},
        # Someone pauses the ad group in Google Ads after the card was shown.
        {_CAMPAIGN: {"status": "ENABLED"}, _AD_GROUP: {"status": "PAUSED"}},
        {_CAMPAIGN: {"status": "PAUSED"}, _AD_GROUP: {"status": "PAUSED"}},
    )
    edits = [
        FieldChange("campaign", _CAMPAIGN, {"status": "PAUSED"}),
        FieldChange("adGroup", _AD_GROUP, {"status": "PAUSED"}),
    ]
    client = _MutateClient(
        {}, {"mutateOperationResponses": [{"campaignResult": {"resourceName": _CAMPAIGN}}]}
    )
    prepared = await _prepared(client, read, edits)
    result = await _applied(client, read, prepared)

    assert client.bodies[0]["validateOnly"] is True
    assert client.bodies[1] == {
        "mutateOperations": [
            {
                "campaignOperation": {
                    "update": {"resourceName": _CAMPAIGN, "status": "PAUSED"},
                    "updateMask": "status",
                }
            }
        ],
        "partialFailure": True,
        "validateOnly": False,
    }
    applied, refused = (parent.effects[0] for parent in result.ledger.parents)
    assert (applied.outcome, applied.external_ref) == ("applied", _CAMPAIGN)
    assert (refused.outcome, refused.error_code) == ("failed", STALE_CODE)
    assert result.after[_CAMPAIGN] == {"status": "PAUSED"}


async def test_edit_reports_an_equal_value_as_already_set_without_a_mutate() -> None:
    read = _LiveState({_CAMPAIGN: {"status": "PAUSED"}})
    client = _MutateClient()
    edits = await _prepared(
        client, read, [FieldChange("campaign", _CAMPAIGN, {"status": "PAUSED"})]
    )
    result = await _applied(client, read, edits)

    assert client.bodies == []
    assert result.ledger.parents[0].skip_reason == "already_set"


async def test_an_unclear_reply_is_settled_by_the_read_back() -> None:
    edits = [
        FieldChange("campaign", _CAMPAIGN, {"status": "PAUSED"}, {"status": "ENABLED"}),
        FieldChange("adGroup", _AD_GROUP, {"status": "PAUSED"}, {"status": "ENABLED"}),
    ]
    read = _LiveState(
        {_CAMPAIGN: {"status": "ENABLED"}, _AD_GROUP: {"status": "ENABLED"}},
        {_CAMPAIGN: {"status": "PAUSED"}, _AD_GROUP: {"status": "ENABLED"}},
    )
    timeout = IntegrationTimeoutError(
        "Google Ads did not reply.", failure_disposition=IntegrationFailureDisposition.AMBIGUOUS
    )

    result = await _applied(_MutateClient(timeout), read, edits)

    assert [parent.effects[0].outcome for parent in result.ledger.parents] == [
        "applied",
        "unverified",
    ]


async def test_an_object_missing_from_the_read_back_keeps_googles_reply() -> None:
    edit = FieldChange("campaign", _CAMPAIGN, {"status": "PAUSED"}, {"status": "ENABLED"})
    read = _LiveState({_CAMPAIGN: {"status": "ENABLED"}}, {})
    client = _MutateClient(
        {"mutateOperationResponses": [{"campaignResult": {"resourceName": _CAMPAIGN}}]}
    )

    result = await _applied(client, read, [edit])

    assert result.ledger.parents[0].effects[0].outcome == "applied"


async def test_a_cancel_during_the_read_back_keeps_what_google_confirmed() -> None:
    edit = FieldChange("campaign", _CAMPAIGN, {"status": "PAUSED"}, {"status": "ENABLED"})
    reads = [{_CAMPAIGN: {"status": "ENABLED"}}, asyncio.CancelledError()]

    async def read(_edits: Sequence[Edit]) -> Mapping[str, Mapping[str, Any]]:
        answer = reads.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    client = _MutateClient(
        {"mutateOperationResponses": [{"campaignResult": {"resourceName": _CAMPAIGN}}]}
    )

    with pytest.raises(asyncio.CancelledError) as caught:
        await _applied(client, read, [edit])

    assert caught.value.ledger.effect_counts == {"applied": 1, "failed": 0, "unverified": 0}


async def test_edit_records_a_partial_failure_per_object() -> None:
    keyword = "customers/333/campaignCriteria/10~2826"
    read = _LiveState(
        {_CAMPAIGN: {"status": "ENABLED"}, _AD_GROUP: {"status": "ENABLED"}},
        {_CAMPAIGN: {"status": "ENABLED"}, _AD_GROUP: {"status": "ENABLED"}},
        {
            _CAMPAIGN: {"status": "ENABLED"},
            _AD_GROUP: {"status": "PAUSED"},
            "campaigns/10/location/2826": {"resourceName": keyword},
        },
    )
    edits = [
        FieldChange("campaign", _CAMPAIGN, {"status": "PAUSED"}),
        FieldChange("adGroup", _AD_GROUP, {"status": "PAUSED"}),
        CriterionChange(
            "campaignCriterion",
            "add",
            key="campaigns/10/location/2826",
            owner=_CAMPAIGN,
            criterion={
                "campaign": _CAMPAIGN,
                "location": {"geoTargetConstant": "geoTargetConstants/2826"},
            },
        ),
    ]
    client = _MutateClient(
        {},
        {
            "mutateOperationResponses": [
                {},
                {"adGroupResult": {"resourceName": _AD_GROUP}},
                {"campaignCriterionResult": {"resourceName": keyword}},
            ],
            "partialFailureError": _partial_failure(0, "Campaign is removed"),
        },
    )
    result = await _applied(client, read, await _prepared(client, read, edits))

    outcomes = [
        (effect.outcome, effect.external_ref, effect.error_code)
        for parent in result.ledger.parents
        for effect in parent.effects
    ]
    assert outcomes == [
        ("failed", None, "CANNOT_MODIFY_REMOVED_CAMPAIGN"),
        ("applied", _AD_GROUP, None),
        ("applied", keyword, None),
    ]


def _search_build() -> CampaignBuild:
    build = CampaignBuild("333")
    # Added out of order on purpose: the request must still send parents first.
    budget = build.create("campaignBudget", {"amountMicros": "5000000"}, label="Budget")
    campaign = build.create("campaign", {"name": "Boots", "campaignBudget": budget}, label="Boots")
    ad_group = build.create("adGroup", {"name": "Hiking", "campaign": campaign}, label="Hiking")
    build.create(
        "adGroupCriterion",
        {"adGroup": ad_group, "keyword": {"text": "hiking boots", "matchType": "PHRASE"}},
        label="hiking boots",
    )
    build.create("campaignCriterion", {"campaign": campaign, "language": {}}, label="English")
    return build


async def test_build_sends_one_atomic_request_with_temporary_names_in_order() -> None:
    client = _MutateClient(
        {
            "mutateOperationResponses": [
                {"campaignBudgetResult": {"resourceName": "customers/333/campaignBudgets/1"}},
                {"campaignResult": {"resourceName": "customers/333/campaigns/2"}},
                {
                    "campaignCriterionResult": {
                        "resourceName": "customers/333/campaignCriteria/2~1000"
                    }
                },
                {"adGroupResult": {"resourceName": "customers/333/adGroups/3"}},
                {"adGroupCriterionResult": {"resourceName": "customers/333/adGroupCriteria/3~4"}},
            ]
        }
    )
    result = await send_build(
        client, _search_build(), login_customer_id="111", family="campaign", operation="create"
    )

    assert client.bodies == [
        {
            "mutateOperations": [
                {
                    "campaignBudgetOperation": {
                        "create": {
                            "amountMicros": "5000000",
                            "resourceName": "customers/333/campaignBudgets/-1",
                        }
                    }
                },
                {
                    "campaignOperation": {
                        "create": {
                            "name": "Boots",
                            "campaignBudget": "customers/333/campaignBudgets/-1",
                            "resourceName": "customers/333/campaigns/-2",
                        }
                    }
                },
                {
                    "campaignCriterionOperation": {
                        "create": {"campaign": "customers/333/campaigns/-2", "language": {}}
                    }
                },
                {
                    "adGroupOperation": {
                        "create": {
                            "name": "Hiking",
                            "campaign": "customers/333/campaigns/-2",
                            "resourceName": "customers/333/adGroups/-3",
                        }
                    }
                },
                {
                    "adGroupCriterionOperation": {
                        "create": {
                            "adGroup": "customers/333/adGroups/-3",
                            "keyword": {"text": "hiking boots", "matchType": "PHRASE"},
                        }
                    }
                },
            ],
            "partialFailure": False,
            "validateOnly": False,
        }
    ]
    assert result.created == {
        "customers/333/campaignBudgets/-1": "customers/333/campaignBudgets/1",
        "customers/333/campaigns/-2": "customers/333/campaigns/2",
        "customers/333/adGroups/-3": "customers/333/adGroups/3",
    }
    assert result.ledger.effect_counts["applied"] == 5


def test_build_refuses_a_reference_to_an_object_it_does_not_create() -> None:
    with pytest.raises(ValueError, match="doesn't create"):
        CampaignBuild("333").create(
            "adGroup", {"campaign": "customers/333/campaigns/-7"}, label="Orphan"
        )


async def test_build_dry_run_rejection_names_the_step() -> None:
    client = _MutateClient({"partialFailureError": _partial_failure(3, "Ad group name is taken")})
    problems = await dry_run_build(
        client, _search_build(), login_customer_id="111", operation="create"
    )

    assert client.bodies[0]["validateOnly"] is True
    assert [(problem.step.label, problem.message) for problem in problems if problem.step] == [
        ("Hiking", "Ad group name is taken")
    ]


async def test_failed_build_records_nothing_as_created() -> None:
    rejection = IntegrationValidationError(
        "Google Ads rejected the request: Budget amount is too low.",
        failure_disposition=IntegrationFailureDisposition.REJECTED,
    )
    result = await send_build(
        _MutateClient(rejection),
        _search_build(),
        login_customer_id="111",
        family="campaign",
        operation="create",
    )

    assert result.created == {}
    assert result.ledger.effect_counts == {"applied": 0, "failed": 5, "unverified": 0}
