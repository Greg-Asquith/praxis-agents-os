# apps/data-science/tests/test_forecast.py

"""The forecast operation end to end in an isolated child, and the holiday covariates."""

import math
from datetime import date

import pytest
from datascience import forecast
from datascience.child_forecast import holiday_covariates, period_days
from datascience.holidays_calendar import daily_shares
from datascience.operations import OPERATIONS
from datascience.self_check import check_forecast
from driver.server import DriverConfig, OperationError, handle_request


def _arguments(**overrides) -> dict:
    return {
        "start": "2026-01-05",
        "frequency": "daily",
        "values": [100 + 30 * math.sin(2 * math.pi * day / 7) for day in range(140)],
        "horizon": 14,
        "holiday_regions": [],
        "covariates": [],
        **overrides,
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"covariates": [{"timing": "known_future", "kind": "number", "values": [1.0] * 140}]},
        {"values": [1.0] * 20, "horizon": 14},
        {"values": [1.0] * 139 + [10**400]},
    ],
    ids=[
        "known-future covariate misses the horizon",
        "history too short",
        "value too large to be finite",
    ],
)
def test_validate_refuses_bad_series(overrides: dict) -> None:
    with pytest.raises(OperationError) as error:
        forecast.validate_forecast(_arguments(**overrides))

    assert error.value.code == "invalid_request"


def test_a_weekly_pattern_forecasts_within_tolerance(config: DriverConfig) -> None:
    arguments = _arguments(
        holiday_regions=["uk"],
        covariates=[{"timing": "known_future", "kind": "number", "values": [0.0] * 154}],
    )
    response = handle_request(
        {
            "operation": "forecast",
            "timeout_seconds": 120,
            "inputs": [],
            "outputs": [],
            "arguments": arguments,
        },
        config=config,
        operations=OPERATIONS,
    )

    result = response["result"]
    expected = [100 + 30 * math.sin(2 * math.pi * day / 7) for day in range(140, 154)]
    median = result["forecast"]["median"]
    assert max(abs(a - b) for a, b in zip(median, expected, strict=True)) < 15
    assert all(
        low <= mid <= high
        for low, mid, high in zip(
            result["forecast"]["low"], median, result["forecast"]["high"], strict=True
        )
    )
    assert result["backtest"]["forecast"]["wape"] < 0.1
    assert result["baseline"] is not None


def test_holiday_shares_weight_regions_by_population() -> None:
    def share(region: str, day: date) -> float:
        return daily_shares(region, {day}).get(day, (0.0, ""))[0]

    assert 0 < share("uk", date(2026, 1, 2)) < 0.2
    assert share("eu", date(2026, 12, 25)) > 0.95
    melbourne_cup = date(2026, 11, 3)
    assert 0.2 < share("au", melbourne_cup) < 0.3
    rows, _ = holiday_covariates(["uk"], period_days("2026-12-01", "monthly", 1), history=1)
    assert rows["uk"][0] > 1.5


def test_start_up_fails_when_the_weights_are_missing(
    config: DriverConfig, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(forecast, "MODEL_DIR", tmp_path / "missing")

    with pytest.raises(OperationError):
        check_forecast(config)
