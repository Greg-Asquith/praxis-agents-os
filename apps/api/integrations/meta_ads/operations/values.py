# apps/api/integrations/meta_ads/operations/values.py

"""Bound provider text and parse finite Meta metric values."""

from datetime import datetime
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
