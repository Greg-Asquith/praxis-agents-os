"""Checks cumulative ceiling composition at framework boundaries."""

import pytest
from pydantic import ValidationError
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RunUsage, UsageLimits

from services.agents.runtime.execute.errors import public_run_error
from services.agents.runtime.usage_limits import (
    BudgetLimitExceeded,
    EffectiveUsageLimits,
    RuntimeUsageLimits,
    SavedUsageLimits,
    intersect_usage_limits,
)


@pytest.mark.parametrize("weight", [0.0, 0.1, 1.0])
@pytest.mark.parametrize("method", ["check_tokens", "check_before_request"])
def test_cached_weight_applies_only_to_total_without_changing_usage(weight, method) -> None:
    from dataclasses import replace
    from decimal import Decimal

    usage = RunUsage(input_tokens=1000, cache_read_tokens=900, output_tokens=10, cost=Decimal("1"))
    original = replace(usage)
    total = 110 + int(900 * weight)
    effective = EffectiveUsageLimits(total_tokens_limit=total, cached_token_weight=weight)
    getattr(effective.to_sdk(), method)(usage)
    with pytest.raises(BudgetLimitExceeded) as error:
        getattr(effective.to_sdk(), method)(replace(usage, output_tokens=11))
    assert error.value.kind == "total_tokens_limit"
    assert error.value.observed_total_tokens == total + 1
    assert usage == original
    for field in ("input_tokens_limit", "output_tokens_limit", "cost_limit"):
        limit = Decimal("0.5") if field == "cost_limit" else 1
        limits = effective.model_copy(update={field: limit}).to_sdk()
        with pytest.raises(BudgetLimitExceeded) as raw_error:
            getattr(limits, "check_cost" if field == "cost_limit" else "check_tokens")(usage)
        assert raw_error.value.kind == field


@pytest.mark.parametrize(("fraction", "expected_requests"), [(0.4, 20), (1.0, 9)])
async def test_long_context_progress_and_runaway_boundary(fraction, expected_requests) -> None:
    from pydantic_ai.messages import ToolCallPart
    from pydantic_ai.usage import RequestUsage

    window = 1_050_000
    requests = []

    def respond(messages, info):
        requests.append(messages)
        parts = [TextPart("Done")] if len(requests) == 20 else [ToolCallPart("advance", {})]
        return ModelResponse(
            parts=parts,
            usage=RequestUsage(input_tokens=int(window * fraction) - 10, output_tokens=10),
        )

    agent = Agent(FunctionModel(respond), name="long_context_backstop")

    @agent.tool_plain
    def advance() -> str:
        return "Continue"

    limits = EffectiveUsageLimits(
        request_limit=20, total_tokens_limit=8 * window, cached_token_weight=0.1
    ).to_sdk()
    if fraction == 0.4:
        result = await agent.run("Complete 20 steps", usage_limits=limits)
        assert result.output == "Done"
    else:
        with pytest.raises(BudgetLimitExceeded) as error:
            await agent.run("Complete 20 steps", usage_limits=limits)
        assert error.value.kind == "total_tokens_limit"
    assert len(requests) == expected_requests


async def test_restored_weighted_usage_keeps_absolute_inherited_boundary() -> None:
    from types import SimpleNamespace

    from pydantic_ai.usage import RequestUsage

    from services.agents.runtime.run_persistence import restored_run_usage

    saved = SavedUsageLimits(
        limits=EffectiveUsageLimits(total_tokens_limit=200, cached_token_weight=0.1)
    )
    restored = SavedUsageLimits.model_validate_json(saved.model_dump_json()).limits
    usage = restored_run_usage(
        SimpleNamespace(usage_json={"input_tokens": 1000, "cache_read_tokens": 900, "requests": 1})
    )
    inherited = EffectiveUsageLimits.from_sdk(restored.to_sdk())
    assert inherited == saved.limits
    requests = []

    def respond(messages, info):
        requests.append(messages)
        return ModelResponse(parts=[TextPart("Done")], usage=RequestUsage(output_tokens=11))

    child = Agent(FunctionModel(respond), name="weighted_budget_child")
    with pytest.raises(BudgetLimitExceeded) as error:
        await child.run("Finish", usage=usage, usage_limits=RuntimeUsageLimits(restored, inherited))
    assert error.value.inherited
    assert error.value.limit == 200
    assert len(requests) == 1
    assert usage.input_tokens == 1000 and usage.cache_read_tokens == 900
    assert usage.output_tokens == 11 and usage.requests == 2
    public = public_run_error(error.value)
    assert public.completion_json == {
        "error_code": "usage_limit_exceeded",
        "tripped_budget": {"kind": "total_tokens", "limit": 200, "scope": "inherited"},
        "observed_total_tokens": 201,
        "requests": 2,
    }
    assert public.message == (
        "This run stopped after counting 201 tokens across 2 requests; "
        "the limit for this run is 200. "
        "Start a new conversation or shorten the context to continue."
    )
    with pytest.raises(BudgetLimitExceeded):
        restored.to_sdk().check_before_request(usage)


@pytest.mark.parametrize(
    ("parent", "child", "expected"),
    [(None, None, None), (3, None, 3), (None, 4, 4), (2, 8, 2), (8, 2, 2)],
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
