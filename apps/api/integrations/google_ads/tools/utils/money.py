# apps/api/integrations/google_ads/tools/utils/money.py

"""Exact account-currency conversion for Google Ads money fields."""

import re
from decimal import Decimal

from integrations.google_ads.constants import GOOGLE_ADS_INT64_MAX

_MICROS_PER_UNIT = Decimal(1_000_000)


def money_to_micros(value: str, *, label: str = "amount") -> int:
    """Converts a positive decimal amount in the account currency to exact micros.

    Raises:
        ValueError: With copy naming `label` when the amount isn't positive, has more than six
            decimal places, or is too large for Google Ads.
    """
    candidate = value.strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", candidate) is None:
        raise ValueError(f"Enter the {label} as a positive decimal number.")
    amount = Decimal(candidate)
    if amount <= 0:
        raise ValueError(f"The {label} must be greater than zero.")
    if len(candidate.partition(".")[2]) > 6:
        raise ValueError(f"The {label} can have at most six decimal places.")
    micros = amount * _MICROS_PER_UNIT
    if int(micros) > GOOGLE_ADS_INT64_MAX:
        raise ValueError(f"The {label} is too large for Google Ads.")
    return int(micros)


def micros_to_money(value: int) -> str:
    return format(Decimal(value) / _MICROS_PER_UNIT, "f")
