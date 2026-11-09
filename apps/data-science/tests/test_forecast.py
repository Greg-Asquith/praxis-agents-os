# apps/data-science/tests/test_forecast.py

"""The forecast operation end to end in an isolated child, and the holiday covariates."""

import math
from datetime import date

import numpy as np
import pytest
from datascience import forecast
from datascience.child_forecast import (
    MAX_STARTING_POINTS,
    count_tested_points,
    holiday_covariates,
    period_days,
    simple_benchmark,
    window_cuts,
)
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
    assert result["backtest"]["starting_points"] > 1
    assert result["backtest"]["tested_points"] > result["backtest"]["holdout"]
    assert result["baseline"] is not None
    assert result["backtest"]["baseline"]["wape"] is not None


def test_test_windows_stop_at_the_limits_and_keep_enough_context() -> None:
    assert window_cuts(52, 8) == [8, 12, 16, 20, 24, 28]
    assert window_cuts(28, 7) == [7, 10, 13, 16]
    # A long window scores enough points on its own, which bounds the forward passes.
    assert window_cuts(10_000, 1_024) == [1_024]
    assert len(window_cuts(10_000, 1)) == MAX_STARTING_POINTS
    assert window_cuts(16, 4) == [4]


def test_tested_points_count_each_period_once_and_skip_gaps() -> None:
    values = np.arange(40.0)
    assert count_tested_points(values, 2, window_cuts(40, 2)) == 7
    values[-1] = np.nan
    assert count_tested_points(values, 2, window_cuts(40, 2)) == 6


def test_simple_benchmark_takes_the_better_method_and_skips_gaps() -> None:
    pattern = np.array([10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0] * 8)
    assert simple_benchmark(pattern, 7, [7], "daily") == {
        "method": "same_period_last_cycle",
        "wape": 0.0,
    }

    level = np.array([10.0] * 20 + [np.nan, 10.0])
    # Weekly's 52-period cycle is longer than the context, so only the average runs.
    assert simple_benchmark(level, 2, [2], "weekly") == {"method": "average", "wape": 0.0}


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
