# apps/data-science/datascience/child_forecast.py

"""Runs one forecast as an isolated child: reads request.json, writes result.json.

Run as ``python -I child_forecast.py`` in the request's directory. The driver has
already checked the request. The child forecasts the horizon, then backtests on the
end of the history, each with and without covariates when there are any.
"""

import calendar
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# The child has no network; never let the Hub client try.
os.environ["HF_HUB_OFFLINE"] = "1"

import numpy as np
import torch
from timestral import TimestralForecaster

from datascience.holidays_calendar import daily_shares

LOW, HIGH = 0.1, 0.9


def period_days(start: str, frequency: str, count: int) -> list[list[date]]:
    """Returns the calendar days each period covers; an hour covers its own date."""
    first = datetime.fromisoformat(start)
    if frequency == "hourly":
        return [[(first + timedelta(hours=index)).date()] for index in range(count)]
    if frequency == "daily":
        return [[first.date() + timedelta(days=index)] for index in range(count)]
    if frequency == "weekly":
        return [
            [first.date() + timedelta(days=7 * index + offset) for offset in range(7)]
            for index in range(count)
        ]
    periods = []
    for index in range(count):
        year, month = divmod(first.month - 1 + index, 12)
        year += first.year
        days = calendar.monthrange(year, month + 1)[1]
        periods.append([date(year, month + 1, day) for day in range(1, days + 1)])
    return periods


def holiday_covariates(
    regions: list[str], periods: list[list[date]], history: int
) -> tuple[dict[str, list[float]], list[dict[str, Any]]]:
    """Returns each region's share per period and the holidays that fall in the horizon."""
    days = {day for period in periods for day in period}
    rows: dict[str, list[float]] = {}
    found = []
    for region in regions:
        shares = daily_shares(region, days)
        rows[region] = [
            round(sum(shares.get(day, (0.0, ""))[0] for day in period), 6) for period in periods
        ]
        horizon_days = sorted({day for period in periods[history:] for day in period})
        found += [
            {
                "date": day.isoformat(),
                "region": region,
                "name": shares[day][1],
                "share": shares[day][0],
            }
            for day in horizon_days
            if day in shares
        ]
    return rows, found


def covariate_arrays(
    request: dict[str, Any], holiday_rows: dict[str, list[float]]
) -> dict[str, np.ndarray]:
    """Groups covariates into Timestral's four (1, C, L) arrays; NaN marks a missing value."""
    groups: dict[str, list[list[float | None]]] = {
        "known_covariates": list(holiday_rows.values()),
        "past_covariates": [],
        "categorical_known_covariates": [],
        "categorical_past_covariates": [],
    }
    for covariate in request["covariates"]:
        prefix = "categorical_" if covariate["kind"] == "category" else ""
        suffix = "known" if covariate["timing"] == "known_future" else "past"
        groups[f"{prefix}{suffix}_covariates"].append(covariate["values"])
    return {name: _array(rows)[None] for name, rows in groups.items() if rows}


def truncate(
    covariates: dict[str, np.ndarray], history: int, holdout: int
) -> dict[str, np.ndarray]:
    """Cuts covariates to a backtest that ends `holdout` steps before the history does."""
    return {
        name: rows[..., : history if "known" in name else history - holdout]
        for name, rows in covariates.items()
    }


def run_one(
    forecaster: TimestralForecaster,
    context: np.ndarray,
    horizon: int,
    covariates: dict[str, np.ndarray],
) -> dict[str, list[float]]:
    forecast = forecaster.forecast(context[None, None], horizon, **covariates)
    return {
        "median": _floats(forecast.median),
        "low": _floats(forecast.quantile(LOW)),
        "high": _floats(forecast.quantile(HIGH)),
        "quantiles": forecast.quantiles[0, 0].double().numpy(),
        "levels": forecast.quantile_levels,
    }


def score(predicted: dict[str, Any], actual: np.ndarray) -> dict[str, Any]:
    """Adds backtest metrics over the observed actuals, or null when there are none."""
    observed = np.isfinite(actual)
    scale = float(np.abs(actual[observed]).sum())
    median = np.array(predicted["median"])
    low, high = np.array(predicted["low"]), np.array(predicted["high"])
    quantiles, levels = predicted.pop("quantiles"), np.array(predicted.pop("levels"))
    if not observed.any() or scale == 0:
        return {**predicted, "wape": None, "coverage": None, "quantile_loss": None}
    errors = actual[observed, None] - quantiles[observed]
    pinball = np.maximum(levels * errors, (levels - 1) * errors).sum()
    inside = (actual[observed] >= low[observed]) & (actual[observed] <= high[observed])
    return {
        **predicted,
        "wape": float(np.abs(actual[observed] - median[observed]).sum() / scale),
        "coverage": float(inside.mean()),
        "quantile_loss": float(2 * pinball / (len(levels) * scale)),
    }


def forecast(request: dict[str, Any]) -> dict[str, Any]:
    values = _array([request["values"]])[0]
    history, horizon = len(values), request["horizon"]
    holdout = min(horizon, history // 4)
    periods = period_days(request["start"], request["frequency"], history + horizon)
    holiday_rows, holidays_found = holiday_covariates(request["holiday_regions"], periods, history)
    covariates = covariate_arrays(request, holiday_rows)
    model_dir = Path(request["model_dir"])
    if not (model_dir / "model.safetensors").is_file():
        raise SystemExit("The model weights are missing")
    forecaster = TimestralForecaster.from_pretrained(model_dir, local_files_only=True)

    main = run_one(forecaster, values, horizon, covariates)
    tested = score(
        run_one(
            forecaster, values[: history - holdout], holdout, truncate(covariates, history, holdout)
        ),
        values[history - holdout :],
    )
    baseline = tested_baseline = None
    if covariates:
        baseline = run_one(forecaster, values, horizon, {})
        tested_baseline = score(
            run_one(forecaster, values[: history - holdout], holdout, {}),
            values[history - holdout :],
        )
    for series in (main, baseline):
        if series:
            del series["quantiles"], series["levels"]
    return {
        "forecast": main,
        "baseline": baseline,
        "backtest": {
            "holdout": holdout,
            "forecast": tested,
            "baseline": tested_baseline,
            "quantile_loss_change": _change(tested, tested_baseline),
        },
        "holiday_covariates": holiday_rows,
        "holidays": holidays_found,
    }


def _change(tested: dict[str, Any], baseline: dict[str, Any] | None) -> float | None:
    if baseline is None or not tested["quantile_loss"] or not baseline["quantile_loss"]:
        return None
    return tested["quantile_loss"] / baseline["quantile_loss"] - 1


def _array(rows: list[list[float | None]]) -> np.ndarray:
    return np.array(
        [[np.nan if value is None else value for value in row] for row in rows], dtype=np.float64
    )


def _floats(values: torch.Tensor) -> list[float]:
    return [float(value) for value in values[0, 0].tolist()]


def main() -> None:
    request = json.loads(Path("request.json").read_text())
    torch.set_grad_enabled(False)
    try:
        result = forecast(request)
    except ValueError as exc:
        # Timestral raises ValueError for degenerate input, such as a constant series of gaps.
        result = {"error": {"code": "invalid_series", "message": str(exc)[:200]}}
    Path("result.json").write_text(json.dumps(result))


if __name__ == "__main__":
    main()
