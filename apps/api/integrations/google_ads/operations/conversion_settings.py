# apps/api/integrations/google_ads/operations/conversion_settings.py

"""Reads the conversion action and account goal settings `google_ads_update_conversions` changes."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .utils import entity_id_boundary_filter, escape_gaql_like_literal, stream_rows

type ConversionSetting = Literal[
    "status",
    "primary",
    "default_value",
    "currency",
    "always_use_default_value",
    "counting",
    "click_through_days",
    "view_through_days",
    "biddable",
]

# Accounts hold a handful of conversion actions; this only stops an unbounded read.
MAX_CONVERSION_ACTIONS = 1_000
MAX_CONVERSION_ACTION_LOOKUP = 101
# Each conversion action setting's field path in Google's JSON names, as the edit seam masks it.
ACTION_PATHS: dict[ConversionSetting, str] = {
    "status": "status",
    "primary": "primaryForGoal",
    "default_value": "valueSettings.defaultValue",
    "currency": "valueSettings.defaultCurrencyCode",
    "always_use_default_value": "valueSettings.alwaysUseDefaultValue",
    "counting": "countingType",
    "click_through_days": "clickThroughLookbackWindowDays",
    "view_through_days": "viewThroughLookbackWindowDays",
}
GOAL_PATHS: dict[ConversionSetting, str] = {"biddable": "biddable"}
_BOOLEANS = frozenset({"primary", "always_use_default_value", "biddable"})
_DAYS = frozenset({"click_through_days", "view_through_days"})
_ACTION_FIELDS = (
    "conversion_action.resource_name, conversion_action.id, conversion_action.name, "
    "conversion_action.status, conversion_action.category, "
    "conversion_action.origin, conversion_action.owner_customer, "
    "conversion_action.primary_for_goal, conversion_action.value_settings.default_value, "
    "conversion_action.value_settings.default_currency_code, "
    "conversion_action.value_settings.always_use_default_value, "
    "conversion_action.counting_type, conversion_action.click_through_lookback_window_days, "
    "conversion_action.view_through_lookback_window_days"
)


def decimal_text(value: Any) -> str | None:
    """A non-negative amount as a canonical decimal string, such as `12.5`; None when it isn't one."""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or amount < 0:
        return None
    return format(amount.normalize(), "f")


def api_value(setting: ConversionSetting, value: Any) -> Any:
    """Converts a setting from card terms to the value Google stores at its path."""
    if value is None:
        return None
    if setting == "default_value":
        return float(value)
    if setting in _DAYS:
        # Google's JSON writes int64 fields as strings.
        return str(value)
    return value


def card_value(setting: ConversionSetting, value: Any) -> Any:
    """Converts a value Google stores to card terms; an unset switch is off."""
    if setting in _BOOLEANS:
        return value is True
    if setting == "default_value":
        return None if value is None else decimal_text(value)
    if setting in _DAYS:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None
    return value if isinstance(value, str) and value else None


def goal_name(category: str, origin: str) -> str:
    """An account goal in words, such as `Purchase from website`, from Google's tokens."""
    return f"{category} from {origin}".replace("_", " ").capitalize()


@dataclass(frozen=True, slots=True)
class LiveConversionAction:
    resource_name: str
    conversion_action_id: str
    name: str
    status: str
    # Google's category and origin tokens, such as `PURCHASE` and `WEBSITE`.
    category: str
    origin: str
    # The account that owns the action, which isn't this one under cross-account tracking.
    owner_customer_id: str
    # By `ACTION_PATHS` path, normalised so equal settings compare equal.
    values: Mapping[str, Any]

    def settings(self) -> dict[ConversionSetting, Any]:
        return {
            setting: card_value(setting, self.values.get(path))
            for setting, path in ACTION_PATHS.items()
        }


@dataclass(frozen=True, slots=True)
class LiveAccountGoal:
    """A category and origin pair, such as purchases on the website, and whether it bids."""

    resource_name: str
    category: str
    origin: str
    values: Mapping[str, Any]


async def list_conversion_actions(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    conversion_action_ids: Sequence[str] = (),
    search: str | None = None,
    minimum_id: int | None = None,
    minimum_id_inclusive: bool = False,
    include_removed: bool = False,
    limit: int = MAX_CONVERSION_ACTIONS,
) -> list[LiveConversionAction]:
    """Returns conversion actions in ID order, searched by name."""
    customer = normalize_customer_id(customer_id)
    if limit < 1 or limit > MAX_CONVERSION_ACTIONS:
        raise ValueError("Google Ads conversion action reads take between 1 and 1,000 actions")
    ids = sorted(set(conversion_action_ids))
    if any(not value.isdigit() for value in ids) or len(ids) > MAX_CONVERSION_ACTION_LOOKUP:
        raise ValueError("Google Ads conversion action reads take at most 101 digit-only ids")
    filters = [] if include_removed else ["conversion_action.status != 'REMOVED'"]
    if ids:
        filters.append(f"conversion_action.id IN ({', '.join(ids)})")
    if search and search.strip():
        filters.append(
            f"conversion_action.name LIKE '%{escape_gaql_like_literal(search.strip())}%'"
        )
    if boundary := entity_id_boundary_filter(
        "conversion_action.id", minimum_id=minimum_id, inclusive=minimum_id_inclusive
    ):
        filters.append(boundary)
    where = f" WHERE {' AND '.join(filters)}" if filters else ""
    payload = await client.post(
        f"customers/{customer}/googleAds:searchStream",
        operation="list_conversion_actions",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={
            "query": f"SELECT {_ACTION_FIELDS} FROM conversion_action{where} "  # noqa: S608 -- fixed fields, digit-only ids, escaped search
            f"ORDER BY conversion_action.id LIMIT {limit}"
        },
    )
    return [
        action
        for row in stream_rows(payload, max_rows=limit)
        if (action := _live_action(customer, row.get("conversionAction"))) is not None
    ]


async def read_account_goals(
    client: GoogleAdsClient, *, customer_id: str, login_customer_id: str
) -> dict[str, LiveAccountGoal]:
    """Returns every account goal by resource name. Google makes them; they can only be updated."""
    customer = normalize_customer_id(customer_id)
    payload = await client.post(
        f"customers/{customer}/googleAds:searchStream",
        operation="read_account_goals",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={
            "query": "SELECT customer_conversion_goal.resource_name, "
            "customer_conversion_goal.category, customer_conversion_goal.origin, "
            "customer_conversion_goal.biddable FROM customer_conversion_goal"
        },
    )
    goals: dict[str, LiveAccountGoal] = {}
    for row in stream_rows(payload, max_rows=MAX_CONVERSION_ACTIONS):
        goal = row.get("customerConversionGoal")
        if not isinstance(goal, Mapping):
            continue
        category, origin = goal.get("category"), goal.get("origin")
        if not isinstance(category, str) or not isinstance(origin, str):
            continue
        name = f"customers/{customer}/customerConversionGoals/{category}~{origin}"
        if goal.get("resourceName") != name:
            continue
        goals[name] = LiveAccountGoal(
            resource_name=name,
            category=category,
            origin=origin,
            values={"biddable": goal.get("biddable") is True},
        )
    return goals


async def read_conversions_last_30_days(
    client: GoogleAdsClient, *, customer_id: str, login_customer_id: str
) -> dict[str, float]:
    """Each conversion action's conversions over the last 30 days, primary or not, by resource name."""
    payload = await client.post(
        f"customers/{normalize_customer_id(customer_id)}/googleAds:searchStream",
        operation="read_conversions_last_30_days",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={
            "query": "SELECT segments.conversion_action, metrics.all_conversions FROM customer "
            "WHERE segments.date DURING LAST_30_DAYS"
        },
    )
    totals: dict[str, float] = {}
    for row in stream_rows(payload, max_rows=MAX_CONVERSION_ACTIONS):
        segments, metrics = row.get("segments"), row.get("metrics")
        if not isinstance(segments, Mapping) or not isinstance(metrics, Mapping):
            continue
        name = segments.get("conversionAction")
        try:
            count = float(metrics.get("allConversions") or 0)
        except (TypeError, ValueError):
            continue
        if isinstance(name, str):
            totals[name] = totals.get(name, 0.0) + count
    return totals


def _live_action(customer: str, action: Any) -> LiveConversionAction | None:
    if not isinstance(action, Mapping):
        return None
    action_id = str(action.get("id") or "")
    name = f"customers/{customer}/conversionActions/{action_id}"
    if not action_id.isdigit() or action.get("resourceName") != name:
        return None
    owner = str(action.get("ownerCustomer") or "").rsplit("/", 1)[-1]
    return LiveConversionAction(
        resource_name=name,
        conversion_action_id=action_id,
        name=str(action.get("name") or "")[:500] or f"Conversion action {action_id}",
        status=str(action.get("status") or ""),
        category=str(action.get("category") or ""),
        origin=str(action.get("origin") or ""),
        owner_customer_id=owner or customer,
        values={
            path: api_value(setting, card_value(setting, _path(action, path)))
            for setting, path in ACTION_PATHS.items()
        },
    )


def _path(body: Mapping[str, Any], path: str) -> Any:
    value: Any = body
    for part in path.split("."):
        value = value.get(part) if isinstance(value, Mapping) else None
    return value
