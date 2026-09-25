# apps/api/integrations/meta_ads/money.py

"""Exact conversions for Meta Ads account currencies."""

from decimal import Decimal, InvalidOperation

_MAX_DIGITS = 256
_MAX_EXPONENT = 256

_OFFSET_ONE = frozenset(
    ["CLP", "COP", "CRC", "HUF", "ISK", "IDR", "JPY", "KRW", "PYG", "TWD", "VND"]
)
_SUPPORTED = _OFFSET_ONE | frozenset(
    [
        "AED",
        "ARS",
        "AUD",
        "BDT",
        "BOB",
        "BRL",
        "CAD",
        "CHF",
        "CNY",
        "CZK",
        "DKK",
        "DZD",
        "EGP",
        "EUR",
        "GBP",
        "GTQ",
        "HKD",
        "HNL",
        "ILS",
        "INR",
        "KES",
        "LKR",
        "MOP",
        "MXN",
        "MYR",
        "NGN",
        "NIO",
        "NOK",
        "NZD",
        "PEN",
        "PHP",
        "PKR",
        "PLN",
        "QAR",
        "RON",
        "SAR",
        "SEK",
        "SGD",
        "THB",
        "TRY",
        "UAH",
        "USD",
        "UYU",
        "ZAR",
    ]
)


def minor_to_amount(value: str | int | Decimal, currency: str) -> Decimal:
    """Converts whole minor units to an exact amount in a supported currency."""
    places = _decimal_places(currency)
    number = _decimal(value)
    if number != number.to_integral_value():
        raise ValueError("Meta Ads minor units must be whole numbers.")
    sign, digits, exponent = number.as_tuple()
    return Decimal((sign, digits, exponent - places))


def amount_to_minor(amount: str | int | Decimal, currency: str) -> int:
    """Converts an exact currency amount, rejecting fractional minor units."""
    places = _decimal_places(currency)
    number = _decimal(amount)
    sign, digits, exponent = number.as_tuple()
    minor = _decimal(Decimal((sign, digits, exponent + places)))
    if minor != minor.to_integral_value():
        raise ValueError("Meta Ads amount contains fractional minor units.")
    return int(minor)


def _decimal_places(currency: str) -> int:
    if currency not in _SUPPORTED:
        raise ValueError("Meta Ads currency is unsupported.")
    return 0 if currency in _OFFSET_ONE else 2


def _decimal(value: str | int | Decimal) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, str | int | Decimal):
        raise TypeError("Meta Ads amounts must use decimal strings, integers, or Decimal.")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError("Meta Ads amount must be a finite number.") from None
    if not number.is_finite():
        raise ValueError("Meta Ads amount must be a finite number.")
    parts = number.as_tuple()
    if (
        len(parts.digits) > _MAX_DIGITS
        or abs(parts.exponent) > _MAX_EXPONENT
        or (number and number.adjusted() >= _MAX_DIGITS)
    ):
        raise ValueError("Meta Ads amount exceeds supported numeric bounds.")
    if not number:
        return Decimal(0)
    significant = len(parts.digits)
    while parts.digits[significant - 1] == 0:
        significant -= 1
    return Decimal(
        (parts.sign, parts.digits[:significant], parts.exponent + len(parts.digits) - significant)
    )
