"""Checks cumulative ceiling composition at framework boundaries."""

from dataclasses import fields

import pytest
from pydantic import ValidationError
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RunUsage, UsageLimits

from services.agents.runtime.usage_limits import (
    BudgetLimitExceeded,
    EffectiveUsageLimits,
    RuntimeUsageLimits,
    SavedUsageLimits,
    intersect_usage_limits,
)


def test_supported_sdk_fields() -> None:
    assert {field.name for field in fields(UsageLimits)} == set(EffectiveUsageLimits.model_fields)
    assert EffectiveUsageLimits.from_sdk(UsageLimits()).to_sdk() == UsageLimits()


@pytest.mark.parametrize(
    ("parent", "child", "expected"),
    [(None, None, None), (3, None, 3), (None, 4, 4), (3, 3, 3), (2, 8, 2), (8, 2, 2)],
)
def test_intersection(parent: int | None, child: int | None, expected: int | None) -> None:
    inherited = EffectiveUsageLimits(request_limit=parent, count_tokens_before_request=True)
    effective = intersect_usage_limits(inherited, EffectiveUsageLimits(request_limit=child))
    assert effective.request_limit == expected
    assert effective.count_tokens_before_request
    assert inherited.request_limit == parent
    assert effective.tool_calls_limit is None
    with pytest.raises(ValidationError):
        inherited.request_limit = 100


@pytest.mark.parametrize("value", [-1, True, "4", 1.5, 2**53])
def test_snapshot_rejects_malformed_ceilings(value: object) -> None:
    with pytest.raises(ValidationError):
        SavedUsageLimits.model_validate({"version": 1, "limits": {"request_limit": value}})


def test_saved_ceilings_never_widen() -> None:
    saved = SavedUsageLimits(limits=EffectiveUsageLimits(request_limit=4))
    for setting in (10, None, 3, 20):
        previous = saved.limits.request_limit
        saved = SavedUsageLimits(
            limits=intersect_usage_limits(saved.limits, EffectiveUsageLimits(request_limit=setting))
        )
        assert saved.limits.request_limit <= previous
        saved = SavedUsageLimits.model_validate(saved.model_dump(mode="json"))
    assert saved.limits.request_limit == 3


@pytest.mark.parametrize("inherited", [False, True])
def test_exact_request_boundary(inherited: bool) -> None:
    ceiling = EffectiveUsageLimits(request_limit=2)
    limits = RuntimeUsageLimits(ceiling, ceiling if inherited else None)
    limits.check_before_request(RunUsage(requests=1))
    with pytest.raises(BudgetLimitExceeded) as error:
        limits.check_before_request(RunUsage(requests=2))
    assert error.value.kind == "request_limit"
    assert error.value.limit == 2
    assert error.value.inherited is inherited
    limits.check_before_tool_call(RunUsage(requests=2, tool_calls=1))


def test_observed_token_overshoot_is_inherited_even_with_stricter_child() -> None:
    parent = EffectiveUsageLimits(total_tokens_limit=10)
    limits = RuntimeUsageLimits(EffectiveUsageLimits(total_tokens_limit=5), parent)
    with pytest.raises(BudgetLimitExceeded) as child_error:
        limits.check_tokens(RunUsage(input_tokens=6))
    assert not child_error.value.inherited
    with pytest.raises(BudgetLimitExceeded) as parent_error:
        limits.check_tokens(RunUsage(input_tokens=11))
    assert parent_error.value.inherited
    assert parent_error.value.limit == 10
    RuntimeUsageLimits(parent).check_tokens(RunUsage(input_tokens=10))


async def test_parent_request_cap_blocks_child_model_request() -> None:
    requests = []

    def respond(messages, info):
        requests.append(messages)
        return ModelResponse(parts=[TextPart("finished")])

    child = Agent(FunctionModel(respond), name="budget_child")
    parent_limits = UsageLimits(request_limit=1)
    shared = RunUsage(requests=1)
    ctx = RunContext(deps=None, model=child.model, usage=shared, usage_limits=parent_limits)
    inherited = EffectiveUsageLimits.from_sdk(ctx.usage_limits)
    with pytest.raises(BudgetLimitExceeded) as error:
        await child.run(
            "Finish the task",
            usage=ctx.usage,
            usage_limits=RuntimeUsageLimits(
                intersect_usage_limits(inherited, EffectiveUsageLimits(request_limit=10)), inherited
            ),
        )
    assert error.value.inherited
    assert requests == []
    assert shared.requests == 1
    assert parent_limits == UsageLimits(request_limit=1)


@pytest.mark.parametrize("version", [True, "1", 0, 2, None])
def test_snapshot_rejects_invalid_version(version: object) -> None:
    with pytest.raises(ValidationError):
        SavedUsageLimits.model_validate({"version": version, "limits": {}})


@pytest.mark.parametrize("extra", ["limits", "snapshot"])
def test_snapshot_rejects_unknown_fields(extra: str) -> None:
    value = {"version": 1, "limits": {}}
    if extra == "limits":
        value["limits"]["unknown_budget"] = 1
    else:
        value["unknown_budget"] = 1
    with pytest.raises(ValidationError):
        SavedUsageLimits.model_validate(value)


@pytest.mark.parametrize(
    ("field", "method", "usage"),
    [
        ("input_tokens_limit", "check_tokens", RunUsage(input_tokens=5)),
        ("output_tokens_limit", "check_tokens", RunUsage(output_tokens=5)),
        ("tool_calls_limit", "check_before_tool_call", RunUsage(tool_calls=5)),
        ("per_request_input_tokens_limit", "check_per_request_input_tokens", 5),
    ],
)
def test_additional_sdk_ceilings_keep_their_check_boundary(field, method, usage) -> None:
    parent = EffectiveUsageLimits.model_validate({field: 4})
    effective = intersect_usage_limits(parent, EffectiveUsageLimits.model_validate({field: 8}))
    assert getattr(effective, field) == 4
    with pytest.raises(BudgetLimitExceeded) as error:
        getattr(RuntimeUsageLimits(effective, parent), method)(usage)
    assert error.value.kind == field
    assert error.value.inherited


def test_decimal_ceiling_round_trips_and_tightens_without_enabling_other_caps() -> None:
    from decimal import Decimal

    parent = EffectiveUsageLimits(cost_limit=Decimal("0.25"))
    effective = intersect_usage_limits(parent, EffectiveUsageLimits(cost_limit=Decimal("1")))
    restored = SavedUsageLimits.model_validate(
        SavedUsageLimits(limits=effective).model_dump(mode="json")
    )
    assert restored.limits.cost_limit == Decimal("0.25")
    assert restored.limits.request_limit is None
    with pytest.raises(BudgetLimitExceeded) as error:
        RuntimeUsageLimits(effective, parent).check_cost(RunUsage(cost=Decimal("0.26")))
    assert error.value.kind == "cost_limit"
    assert error.value.inherited
