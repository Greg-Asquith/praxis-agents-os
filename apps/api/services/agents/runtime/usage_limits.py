# apps/api/services/agents/runtime/usage_limits.py

"""Composes absolute usage ceilings and preserves exhaustion ownership."""

from dataclasses import fields, replace
from decimal import Decimal
from math import ceil
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import UsageLimitExceeded
from pydantic_ai.usage import RunUsage, UsageLimits

if TYPE_CHECKING:
    from services.agents.runtime.progress_review.grant import RequestGrant

Ceiling = Annotated[int, Field(strict=True, ge=0, le=2**53 - 1)]
CachedTokenWeight = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
EFFECTIVE_USAGE_LIMITS_KEY = "effective_usage_limits"
_LOCAL_FIELDS = frozenset({"cached_token_weight", "hard_request_limit"})


class EffectiveUsageLimits(BaseModel):
    """Stores an immutable copy of every supported framework ceiling."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    # The agent's step limit, which progress reviews can raise.
    request_limit: Ceiling | None = None
    # Request ceilings that no review can raise, such as a schedule's `max_requests`.
    hard_request_limit: Ceiling | None = None
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
    cached_token_weight: CachedTokenWeight = 1.0

    @classmethod
    def from_sdk(cls, limits: UsageLimits) -> "EffectiveUsageLimits":
        """Copies framework fields and rejects unreviewed SDK changes."""
        sdk_fields = set(cls.model_fields) - _LOCAL_FIELDS
        if {field.name for field in fields(UsageLimits)} != sdk_fields:
            raise RuntimeError("The framework usage-limit fields need review")
        return cls.model_validate(
            {name: getattr(limits, name) for name in sdk_fields}
            | {
                "cached_token_weight": getattr(limits, "cached_token_weight", 1.0),
                "hard_request_limit": getattr(limits, "hard_request_limit", None),
            }
        )

    def to_sdk(self) -> UsageLimits:
        return RuntimeUsageLimits(self)


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
        if name == "cached_token_weight":
            ceilings[name] = max(supplied, default=1.0)
            continue
        ceilings[name] = (
            any(supplied) if name == "count_tokens_before_request" else min(supplied, default=None)
        )
    return EffectiveUsageLimits.model_validate(ceilings)


class BudgetLimitExceeded(UsageLimitExceeded):
    """Identifies a ceiling at its framework check boundary."""

    def __init__(
        self,
        *,
        kind: str,
        limit: int | Decimal,
        inherited: bool,
        observed: RunUsage | int,
        progress_review: dict[str, Any] | None = None,
    ) -> None:
        super().__init__("The agent run reached its usage budget.")
        self.kind = kind
        self.limit = limit
        self.inherited = inherited
        self.progress_review = progress_review
        self.observed_total_tokens = (
            observed.total_tokens if isinstance(observed, RunUsage) else None
        )


class RuntimeUsageLimits(UsageLimits):
    """Uses framework checks with typed local or inherited attribution."""

    def __init__(
        self,
        effective: EffectiveUsageLimits,
        inherited: EffectiveUsageLimits | None = None,
        *,
        grant: "RequestGrant | None" = None,
    ) -> None:
        super().__init__(**effective.model_dump(exclude=_LOCAL_FIELDS))
        self.cached_token_weight = effective.cached_token_weight
        self.hard_request_limit = effective.hard_request_limit
        self.grant = grant
        self._effective = effective
        self._inherited = inherited

    @property
    def family_step_size(self) -> int | None:
        """The root run's step limit, which each review grant adds again."""
        return (self._inherited or self._effective).request_limit

    @property
    def family_request_ceiling(self) -> int | None:
        step = self.family_step_size
        return None if step is None else step + self._granted

    def hard_request_limit_reached(self, usage: RunUsage) -> bool:
        hard = self._effective.hard_request_limit
        return hard is not None and usage.requests >= hard

    @property
    def _granted(self) -> int:
        return self.grant.granted if self.grant is not None else 0

    def _ceilings(self, limits: EffectiveUsageLimits) -> list[tuple[str, int | Decimal, bool]]:
        """Lists enabled ceilings, with the grant added to each step-derived request ceiling."""
        ceilings: list[tuple[str, int | Decimal, bool]] = []
        if limits.hard_request_limit is not None:
            ceilings.append(("request_limit", limits.hard_request_limit, False))
        for field in fields(UsageLimits):
            ceiling = getattr(limits, field.name)
            if ceiling is None or field.name == "count_tokens_before_request":
                continue
            grantable = field.name == "request_limit"
            ceilings.append(
                (field.name, ceiling + self._granted if grantable else ceiling, grantable)
            )
        return ceilings

    def _check(self, method: str, value: RunUsage | int, **kwargs: bool) -> None:
        check = getattr(UsageLimits, method)
        candidates = [(self._inherited, True)] if self._inherited else []
        candidates.append((self._effective, False))
        for limits, inherited in candidates:
            # Isolated SDK checks preserve raw input/output limits and typed attribution.
            for name, ceiling, grantable in self._ceilings(limits):
                observed = value
                if name == "total_tokens_limit" and isinstance(value, RunUsage):
                    cached = min(value.input_tokens, max(0, value.cache_read_tokens))
                    observed = replace(
                        value,
                        input_tokens=value.input_tokens
                        - cached
                        + ceil(Decimal(str(limits.cached_token_weight)) * cached),
                    )
                isolated = UsageLimits(**{"request_limit": None, name: ceiling})
                try:
                    check(isolated, observed, **kwargs)
                except UsageLimitExceeded as exc:
                    raise BudgetLimitExceeded(
                        kind=name,
                        limit=ceiling,
                        inherited=inherited,
                        observed=observed,
                        progress_review=(
                            self.grant.escalation_evidence() if grantable and self.grant else None
                        ),
                    ) from exc

    def check_before_request(self, usage: RunUsage) -> None:
        self._check("check_before_request", usage)

    def check_tokens(self, usage: RunUsage) -> None:
        self._check("check_tokens", usage)

    def _check_token_limits(self, usage: RunUsage) -> None:
        # Pydantic AI calls this directly on streamed chunks and provisional continuation usage.
        self._check("_check_token_limits", usage)

    def check_before_tool_call(self, projected_usage: RunUsage) -> None:
        self._check("check_before_tool_call", projected_usage)

    def check_per_request_input_tokens(self, request_input_tokens: int) -> None:
        self._check("check_per_request_input_tokens", request_input_tokens)

    def check_cost(self, usage: RunUsage, *, warn_if_cost_unavailable: bool = True) -> None:
        self._check("check_cost", usage, warn_if_cost_unavailable=warn_if_cost_unavailable)
