# apps/api/integrations/meta_ads/throttle.py

"""Best-effort process-local throttle state for Meta Ads accounts."""

import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from time import monotonic
from typing import Annotated, Any

from pydantic import Field, Json, OnErrorOmit, TypeAdapter

from core.exceptions.integration import IntegrationFailureDisposition, IntegrationRateLimitError

_MAX_KEYS = 256
_IDLE_TTL_SECONDS = 300.0
_MAX_HEADER_CHARS = 16_384
_MAX_WAIT_SECONDS = 86_400.0
_USAGE_HEADERS = TypeAdapter(dict[str, OnErrorOmit[Json[dict[str, Any]]]])
_USAGE_NUMBERS = TypeAdapter(
    dict[str, OnErrorOmit[Annotated[float, Field(strict=True, ge=0, le=_MAX_WAIT_SECONDS)]]]
)


@dataclass
class _Usage:
    deadlines: dict[str, float] = field(default_factory=dict)
    last_used_at: float = 0

    @property
    def regain_at(self) -> float:
        return max(self.deadlines.values(), default=0)


_accounts: dict[str, _Usage] = {}


def record_usage(account_id: str, headers: Mapping[str, str]) -> None:
    """Records bounded usage values without retaining provider header text."""
    if not account_id:
        return
    now = monotonic()
    _evict(now)
    observations, _ = _parse_usage(headers)
    if not observations:
        return
    state = _accounts.get(account_id)
    if state is None:
        if len(_accounts) >= _MAX_KEYS:
            oldest = min(_accounts, key=lambda key: _accounts[key].last_used_at)
            _accounts.pop(oldest)
        state = _Usage()
        _accounts[account_id] = state
    for source, (utilisation, wait) in observations.items():
        if utilisation < 100:
            state.deadlines.pop(source, None)
        elif wait is not None and wait > 0:
            state.deadlines[source] = max(state.deadlines.get(source, 0), now + wait)
    state.last_used_at = now


def ensure_account_available(account_id: str) -> None:
    """Rejects an Insights request while a known account throttle remains active."""
    now = monotonic()
    _evict(now)
    state = _accounts.get(account_id)
    if state is None:
        return
    state.last_used_at = now
    if state.regain_at > now:
        raise IntegrationRateLimitError(
            _message(state.regain_at - now),
            provider_key="meta_ads",
            operation="run_insights",
            failure_disposition=IntegrationFailureDisposition.NOT_DISPATCHED,
        )


def throttle_message(headers: Mapping[str, str]) -> str:
    """Returns rate-limit guidance with Meta's wait time when available."""
    return _message(_parse_usage(headers)[1])


def _message(wait_seconds: float | None) -> str:
    if wait_seconds is not None and wait_seconds > 0:
        minutes = math.ceil(wait_seconds / 60)
        unit = "minute" if minutes == 1 else "minutes"
        return f"Meta Ads has reached its request limit. Try again in {minutes} {unit}."
    return "Meta Ads has reached its request limit. Wait a few minutes before trying again."


def _parse_usage(
    headers: Mapping[str, str],
) -> tuple[dict[str, tuple[float, float | None]], float | None]:
    parsed = _USAGE_HEADERS.validate_python(
        {name.lower(): raw for name, raw in headers.items() if len(raw) <= _MAX_HEADER_CHARS}
    )
    insights = _USAGE_NUMBERS.validate_python(parsed.get("x-fb-ads-insights-throttle", {}))
    account = _USAGE_NUMBERS.validate_python(parsed.get("x-ad-account-usage", {}))
    business, business_wait, insights_wait = _business_usage(
        parsed.get("x-business-use-case-usage", {})
    )
    account_wait = account.get("reset_time_duration")
    observations = dict(business)
    if "acc_id_util_pct" in account:
        observations["account"] = (account["acc_id_util_pct"], account_wait)
    # A wait-only account header can qualify Insights in the same response.
    # A header with account utilisation belongs to that account quota instead.
    if "acc_id_util_pct" not in account and account_wait is not None:
        insights_wait = max(insights_wait or 0, account_wait)
    for key in ("app_id_util_pct", "acc_id_util_pct"):
        if key in insights:
            observations[f"insights:{key}"] = (insights[key], insights_wait)
    waits = [wait for wait in (account_wait, business_wait) if wait is not None]
    return observations, max(waits, default=None)


def _business_usage(
    usage: dict[str, Any],
) -> tuple[dict[str, tuple[float, float | None]], float | None, float | None]:
    utilisations: list[float] = []
    saturated_waits: list[float] = []
    insights_hints: list[float] = []
    waits: list[float] = []
    for entry in _business_entries(usage):
        values = _USAGE_NUMBERS.validate_python(entry)
        minutes = values.get("estimated_time_to_regain_access")
        wait = min(minutes * 60, _MAX_WAIT_SECONDS) if minutes is not None else None
        if wait is not None:
            waits.append(wait)
        if entry.get("type") not in (None, "ads_insights"):
            continue
        utilisation = max(
            (values[key] for key in ("call_count", "total_cputime", "total_time") if key in values),
            default=None,
        )
        if utilisation is None and wait is not None:
            insights_hints.append(wait)
        if utilisation is not None:
            utilisations.append(utilisation)
            if utilisation >= 100 and wait is not None:
                saturated_waits.append(wait)
    observations = {}
    if utilisations:
        observations["business_insights"] = (max(utilisations), max(saturated_waits, default=None))
    return observations, max(waits, default=None), max(insights_hints, default=None)


def _business_entries(usage: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for entries in usage.values():
        if isinstance(entries, list):
            yield from (entry for entry in entries if isinstance(entry, dict))


def _evict(now: float) -> None:
    stale = [
        key
        for key, state in _accounts.items()
        if now - state.last_used_at >= _IDLE_TTL_SECONDS and now >= state.regain_at
    ]
    for key in stale:
        _accounts.pop(key, None)
