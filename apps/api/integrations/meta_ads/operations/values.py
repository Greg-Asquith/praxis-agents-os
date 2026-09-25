# apps/api/integrations/meta_ads/operations/values.py

"""Bound provider text and parse finite Meta metric values."""

from decimal import Decimal, InvalidOperation
from typing import Any

from core.exceptions.integration import IntegrationValidationError


def bounded_string(value: Any, maximum: int = 512) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise invalid_response("Meta Ads returned invalid text.")
    return value[:maximum]


def numeric_value(value: Any, *, count: bool = False) -> int | float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise invalid_response("Meta Ads returned an invalid metric value.")
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
        raise invalid_response("Meta Ads returned an invalid metric value.") from None


def invalid_response(message: str) -> IntegrationValidationError:
    return IntegrationValidationError(message, provider_key="meta_ads", operation="run_insights")
