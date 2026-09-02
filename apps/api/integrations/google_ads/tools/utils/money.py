# apps/api/integrations/google_ads/tools/utils/money.py

"""Exact account-currency conversion for Google Ads money fields."""

from decimal import Decimal, InvalidOperation

from pydantic_ai import ModelRetry

from integrations.google_ads.constants import GOOGLE_ADS_INT64_MAX

_MICROS_PER_UNIT = Decimal(1_000_000)


def money_to_micros(value: str) -> int:
    """Convert a positive decimal currency string to an exact provider int64."""
    candidate = value.strip()
    if not candidate or any(character not in "0123456789." for character in candidate):
        raise ModelRetry("Enter the budget amount as a positive decimal number.")
    try:
        decimal_value = Decimal(candidate)
    except InvalidOperation as exc:
        raise ModelRetry("Enter the budget amount as a positive decimal number.") from exc
    micros = decimal_value * _MICROS_PER_UNIT
    if decimal_value <= 0:
        raise ModelRetry("The budget amount must be greater than zero.")
    if micros != micros.to_integral_value():
        raise ModelRetry("The budget amount can have at most six decimal places.")
    integer_micros = int(micros)
    if integer_micros > GOOGLE_ADS_INT64_MAX:
        raise ModelRetry("The budget amount is too large for Google Ads.")
    return integer_micros


def micros_to_money(value: int) -> str:
    return format(Decimal(value) / _MICROS_PER_UNIT, "f")
