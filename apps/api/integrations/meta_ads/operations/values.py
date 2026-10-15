# apps/api/integrations/meta_ads/operations/values.py

"""Bound provider text and parse finite Meta metric values."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from core.exceptions.integration import IntegrationValidationError

from ..money import is_supported_currency, minor_to_amount

ACCOUNT_STATUSES = {
    1: "ACTIVE",
    2: "DISABLED",
    3: "UNSETTLED",
    7: "PENDING_RISK_REVIEW",
    8: "PENDING_SETTLEMENT",
    9: "IN_GRACE_PERIOD",
    100: "PENDING_CLOSURE",
    101: "CLOSED",
    201: "ANY_ACTIVE",
    202: "ANY_CLOSED",
}
_DISABLE_REASONS = {
    1: "Advertising policy violation",
    2: "Ad review",
    3: "Payment risk",
    4: "Grey account review",
    5: "Integrity review",
    6: "Business integrity review",
    7: "Permanent closure",
    8: "Unused account",
    9: "Account review",
}


def account_status(value: Any) -> str:
    code = numeric_value(value, count=True, operation="get_account")
    return ACCOUNT_STATUSES.get(code, "UNKNOWN").replace("_", " ").capitalize()


def disable_reason(value: Any) -> str | None:
    code = numeric_value(value, count=True, operation="get_account")
    return None if code in (None, 0) else _DISABLE_REASONS.get(code, "Unknown reason")


def require_currency(currency: Any, *, operation: str) -> str:
    if not currency:
        raise invalid_response(
            "Meta Ads account currency is missing. Use Look for New Resources on the connection.",
            operation=operation,
        )
    if not isinstance(currency, str) or not is_supported_currency(currency):
        raise invalid_response("Meta Ads account currency is unsupported.", operation=operation)
    return currency


def money_value(value: Any, currency: str, *, operation: str) -> str | None:
    if value is None or value == "":
        return None
    try:
        return format(minor_to_amount(value, currency), "f")
    except (TypeError, ValueError):
        raise invalid_response(
            "Meta Ads returned an invalid currency amount.", operation=operation
        ) from None


def minimum_budget_problem(
    *,
    kind: str,
    amount: str,
    minimum: str | None,
    days: int | None,
    currency: str,
    subject: str,
) -> str | None:
    """Checks a daily or lifetime budget against Meta's daily minimum for `subject`."""
    if minimum is None:
        return None
    floor = Decimal(minimum)
    if kind == "daily" and Decimal(amount) < floor:
        return f"The minimum daily budget for {subject} is {minimum} {currency}."
    if kind == "lifetime" and days and Decimal(amount) < floor * days:
        return (
            f"Over {days} days, the minimum lifetime budget for {subject} is "
            f"{format(floor * days, 'f')} {currency}."
        )
    return None


def squashed_text(value: Any, maximum: int) -> str | None:
    """Collapses whitespace and bounds provider text; None for anything but non-empty text."""
    return " ".join(value.split())[:maximum] or None if isinstance(value, str) else None


def excerpt(value: Any, maximum: int) -> str | None:
    """Collapses whitespace and shortens provider text to `maximum` characters with an ellipsis."""
    text = " ".join(value.split()) if isinstance(value, str) else ""
    if len(text) <= maximum:
        return text or None
    return text[: maximum - 1].rstrip() + "…"


def bounded_string(value: Any, *, operation: str, maximum: int = 512) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise invalid_response("Meta Ads returned invalid text.", operation=operation)
    return value[:maximum]


def iso_datetime(value: Any, *, operation: str) -> str | None:
    text = bounded_string(value, operation=operation)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).isoformat()
    except ValueError:
        raise invalid_response("Meta Ads returned an invalid time.", operation=operation) from None


def iso_date(value: Any, *, operation: str) -> str:
    try:
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except ValueError:
        raise invalid_response(
            "Meta Ads returned an invalid report date.", operation=operation
        ) from None
    return value


def numeric_value(value: Any, *, operation: str, count: bool = False) -> int | float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise invalid_response("Meta Ads returned an invalid metric value.", operation=operation)
    try:
        number = Decimal(str(value))
        if (
            not number.is_finite()
            or number.adjusted() > 308
            or (count and number != number.to_integral_value())
        ):
            raise InvalidOperation
        result = int(number) if count else float(number)
        if not count and not Decimal(str(result)).is_finite():
            raise InvalidOperation
        return result
    except (InvalidOperation, ValueError, OverflowError):
        raise invalid_response(
            "Meta Ads returned an invalid metric value.", operation=operation
        ) from None


def invalid_response(message: str, *, operation: str) -> IntegrationValidationError:
    return IntegrationValidationError(message, provider_key="meta_ads", operation=operation)
