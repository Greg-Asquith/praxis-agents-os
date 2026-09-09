# apps/api/services/agents/runtime/usage_limits.py

"""Composes absolute usage ceilings and preserves exhaustion ownership."""

from dataclasses import fields
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import UsageLimitExceeded
from pydantic_ai.usage import RunUsage, UsageLimits

Ceiling = Annotated[int, Field(strict=True, ge=0, le=2**53 - 1)]
EFFECTIVE_USAGE_LIMITS_KEY = "effective_usage_limits"


class EffectiveUsageLimits(BaseModel):
    """Stores an immutable copy of every supported framework ceiling."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    request_limit: Ceiling | None = None
    tool_calls_limit: Ceiling | None = None
    input_tokens_limit: Ceiling | None = None
    output_tokens_limit: Ceiling | None = None
    total_tokens_limit: Ceiling | None = None
    per_request_input_tokens_limit: Ceiling | None = None
    cost_limit: (
        Annotated[
            Decimal,
            Field(ge=0, allow_inf_nan=False, max_digits=24, decimal_places=12, strict=False),
        ]
        | None
    ) = None
    count_tokens_before_request: bool = False

    @classmethod
    def from_sdk(cls, limits: UsageLimits) -> "EffectiveUsageLimits":
        """Copies framework fields and rejects unreviewed SDK changes."""
        if {field.name for field in fields(UsageLimits)} != set(cls.model_fields):
            raise RuntimeError("The framework usage-limit fields need review")
        return cls.model_validate({name: getattr(limits, name) for name in cls.model_fields})

    def to_sdk(self) -> UsageLimits:
        return UsageLimits(**self.model_dump())


class SavedUsageLimits(BaseModel):
    """Validates the bounded, server-owned ceiling snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    limits: EffectiveUsageLimits


def intersect_usage_limits(*limits: EffectiveUsageLimits | None) -> EffectiveUsageLimits:
    """Tightens ceilings without subtracting cumulative usage."""
    values = [limit.model_dump() for limit in limits if limit is not None]
    ceilings = {}
    for name in EffectiveUsageLimits.model_fields:
        supplied = [value[name] for value in values if value[name] is not None]
        ceilings[name] = (
            any(supplied) if name == "count_tokens_before_request" else min(supplied, default=None)
        )
    return EffectiveUsageLimits.model_validate(ceilings)


class BudgetLimitExceeded(UsageLimitExceeded):
    """Identifies a ceiling at its framework check boundary."""

    def __init__(self, *, kind: str, limit: int | Decimal, inherited: bool) -> None:
        super().__init__("The agent run reached its usage budget.")
        self.kind = kind
        self.limit = limit
        self.inherited = inherited


class RuntimeUsageLimits(UsageLimits):
    """Uses framework checks with typed local or inherited attribution."""

    def __init__(
        self, effective: EffectiveUsageLimits, inherited: EffectiveUsageLimits | None = None
    ) -> None:
        super().__init__(**effective.model_dump())
        self._inherited = inherited

    def _check(self, method: str, value: RunUsage | int, **kwargs: bool) -> None:
        check = getattr(UsageLimits, method)
        candidates = [(self._inherited.to_sdk(), True)] if self._inherited else []
        candidates.append((self, False))
        for limits, inherited in candidates:
            try:
                check(limits, value, **kwargs)
            except UsageLimitExceeded as exc:
                # Isolated framework checks identify the field without parsing exception text.
                for name in EffectiveUsageLimits.model_fields:
                    ceiling = getattr(limits, name)
                    if ceiling is None or name == "count_tokens_before_request":
                        continue
                    isolated = UsageLimits(**{"request_limit": None, name: ceiling})
                    try:
                        check(isolated, value, **kwargs)
                    except UsageLimitExceeded:
                        raise BudgetLimitExceeded(
                            kind=name, limit=ceiling, inherited=inherited
                        ) from exc
                raise

    def check_before_request(self, usage: RunUsage) -> None:
        self._check("check_before_request", usage)

    def check_tokens(self, usage: RunUsage) -> None:
        self._check("check_tokens", usage)

    def check_before_tool_call(self, projected_usage: RunUsage) -> None:
        self._check("check_before_tool_call", projected_usage)

    def check_per_request_input_tokens(self, request_input_tokens: int) -> None:
        self._check("check_per_request_input_tokens", request_input_tokens)

    def check_cost(self, usage: RunUsage, *, warn_if_cost_unavailable: bool = True) -> None:
        self._check("check_cost", usage, warn_if_cost_unavailable=warn_if_cost_unavailable)
