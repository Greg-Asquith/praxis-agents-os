from decimal import Decimal, localcontext

import pytest

from integrations.meta_ads.money import amount_to_minor, minor_to_amount


@pytest.mark.parametrize("currency", ["USD", "EUR", "GBP", "AED", "BDT", "ZAR"])
@pytest.mark.parametrize("value", ["0", "1", "12345", "-120", "123456789012345678901234567890"])
def test_offset_100_round_trip(currency: str, value: str) -> None:
    amount = minor_to_amount(value, currency)
    assert isinstance(amount, Decimal)
    assert amount_to_minor(amount, currency) == int(value)


@pytest.mark.parametrize(
    "currency", ["CLP", "COP", "CRC", "HUF", "ISK", "IDR", "JPY", "KRW", "PYG", "TWD", "VND"]
)
def test_offset_one_round_trip(currency: str) -> None:
    assert minor_to_amount("12345", currency) == Decimal("12345")
    assert amount_to_minor("12345", currency) == 12345


def test_exact_amounts_ignore_ambient_decimal_precision() -> None:
    with localcontext() as context:
        context.prec = 2
        assert minor_to_amount("1234567", "EUR") == Decimal("12345.67")
        assert amount_to_minor("12345.67", "EUR") == 1234567


@pytest.mark.parametrize("currency", ["XYZ", "BHD", "usd", ""])
def test_unknown_currency_raises(currency: str) -> None:
    with pytest.raises(ValueError, match="currency is unsupported"):
        minor_to_amount("123", currency)
    with pytest.raises(ValueError, match="currency is unsupported"):
        amount_to_minor("1.23", currency)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "invalid", ""])
def test_invalid_amounts_raise(value: str) -> None:
    with pytest.raises(ValueError, match="finite number"):
        minor_to_amount(value, "EUR")
    with pytest.raises(ValueError, match="finite number"):
        amount_to_minor(value, "EUR")


@pytest.mark.parametrize("value", [1.23, True, None])
def test_float_and_non_numeric_inputs_are_rejected(value: object) -> None:
    with pytest.raises(TypeError, match="decimal strings"):
        amount_to_minor(value, "EUR")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="decimal strings"):
        minor_to_amount(value, "EUR")  # type: ignore[arg-type]


def test_fractional_minor_units_are_not_rounded() -> None:
    with pytest.raises(ValueError, match="whole numbers"):
        minor_to_amount("1.1", "EUR")
    with pytest.raises(ValueError, match="fractional minor units"):
        amount_to_minor("1.001", "EUR")
    with pytest.raises(ValueError, match="fractional minor units"):
        amount_to_minor("1.1", "JPY")


@pytest.mark.parametrize(
    "value", ["1e-1000030", "1e10000", "1e1000000", "0e1000000", "1" * 257, "1e257"]
)
@pytest.mark.parametrize("convert", [amount_to_minor, minor_to_amount])
def test_extreme_coefficients_and_exponents_are_rejected(value, convert):
    with pytest.raises(ValueError, match="supported numeric bounds"):
        convert(value, "USD")


@pytest.mark.parametrize("currency", ["USD", "JPY"])
@pytest.mark.parametrize("value", ["1e200", "-1e200", "1" * 254, "0.000", "1.0000"])
def test_bounded_scientific_and_long_coefficients_round_trip(currency, value):
    amount = Decimal(value)
    assert minor_to_amount(amount_to_minor(amount, currency), currency) == amount


def test_exact_conversion_ignores_ambient_exponent_limits():
    with localcontext() as context:
        context.Emax = 2
        context.Emin = -2
        assert amount_to_minor("1e100", "USD") == 10**102
        assert minor_to_amount(10**102, "USD") == Decimal("1e100")


@pytest.mark.parametrize("value", ["1" * 256, "1e255"])
def test_amount_conversion_rejects_minor_unit_expansion_beyond_bounds(value):
    with pytest.raises(ValueError, match="supported numeric bounds"):
        amount_to_minor(value, "USD")


@pytest.mark.parametrize("currency", ["USD", "JPY"])
def test_largest_bounded_minor_amount_round_trips(currency):
    minor = 10**255
    assert amount_to_minor(minor_to_amount(minor, currency), currency) == minor


@pytest.mark.parametrize("value", ["0e-256", "0e256", "-0e-256"])
def test_bounded_zero_exponents_round_trip(value):
    assert amount_to_minor(value, "USD") == 0
    assert amount_to_minor(minor_to_amount(value, "USD"), "USD") == 0


@pytest.mark.parametrize("currency", ["USD", "JPY"])
def test_long_exact_fractional_notation_round_trips(currency):
    minor = Decimal("1." + "0" * 255)
    assert amount_to_minor(minor_to_amount(minor, currency), currency) == 1
