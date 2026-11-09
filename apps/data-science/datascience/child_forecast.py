# apps/data-science/datascience/child_forecast.py

"""Runs one forecast as an isolated child: reads request.json, writes result.json.

Run as ``python -I child_forecast.py`` in the request's directory. The driver has
already checked the request. The child forecasts the horizon, then backtests from several
starting points near the end of the history, each with and without covariates when there
are any, and scores simple benchmarks over the same periods.
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
# One test window can flatter or punish a forecast, so windows repeat until these limits.
MAX_STARTING_POINTS = 6
ENOUGH_TESTED_POINTS = 64
MIN_TEST_CONTEXT = 12
# Bounds the extra forward passes on long histories; the forecast itself reads all of it.
MAX_TEST_CONTEXT = 2_048
SEASONS = {"hourly": 24, "daily": 7, "weekly": 52, "monthly": 12}


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


def window_cuts(history: int, holdout: int) -> list[int]:
    """Returns each test window's distance from the end of the history, latest first."""
    step = max(1, holdout // 2)
    least_context = max(MIN_TEST_CONTEXT, holdout)
    cuts = [holdout]
    while (
        len(cuts) < MAX_STARTING_POINTS
        and len(cuts) * holdout < ENOUGH_TESTED_POINTS
        and history - cuts[-1] - step >= least_context
    ):
        cuts.append(cuts[-1] + step)
    return cuts


def count_tested_points(values: np.ndarray, holdout: int, cuts: list[int]) -> int:
    """Counts the actual values scored; windows overlap, so each period counts once."""
    history = len(values)
    periods = {period for cut in cuts for period in range(history - cut, history - cut + holdout)}
    return sum(bool(np.isfinite(values[period])) for period in periods)


def window(
    covariates: dict[str, np.ndarray], first: int, end: int, holdout: int
) -> dict[str, np.ndarray]:
    """Cuts covariates to a test whose context runs from `first` up to `end`."""
    return {
        name: rows[..., first : end + holdout if "known" in name else end]
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


def score(predictions: list[dict[str, Any]], actuals: list[np.ndarray]) -> dict[str, Any]:
    """Returns backtest metrics pooled over the observed actuals, or null when there are none."""
    actual = np.concatenate(actuals)
    observed = np.isfinite(actual)
    scale = float(np.abs(actual[observed]).sum())
    if not observed.any() or scale == 0:
        return {"wape": None, "coverage": None, "quantile_loss": None}
    median = np.concatenate([np.array(item["median"]) for item in predictions])
    low = np.concatenate([np.array(item["low"]) for item in predictions])
    high = np.concatenate([np.array(item["high"]) for item in predictions])
    quantiles = np.concatenate([item["quantiles"] for item in predictions])
    levels = np.array(predictions[0]["levels"])
    errors = actual[observed, None] - quantiles[observed]
    pinball = np.maximum(levels * errors, (levels - 1) * errors).sum()
    inside = (actual[observed] >= low[observed]) & (actual[observed] <= high[observed])
    return {
        "wape": float(np.abs(actual[observed] - median[observed]).sum() / scale),
        "coverage": float(inside.mean()),
        "quantile_loss": float(2 * pinball / (len(levels) * scale)),
    }


def simple_benchmark(
    values: np.ndarray, holdout: int, cuts: list[int], frequency: str
) -> dict[str, Any]:
    """Returns the lower error of the two forecasts a forecast must beat to add anything."""
    history, season = len(values), SEASONS[frequency]
    methods = ["average"]
    if history - cuts[-1] >= season:
        methods.append("same_period_last_cycle")
    best: dict[str, Any] = {"method": "average", "wape": None}
    for method in methods:
        predicted, actual = [], []
        for cut in cuts:
            context = values[: history - cut]
            predicted.append(_simple_forecast(context, holdout, method, season))
            actual.append(values[history - cut : history - cut + holdout])
        error = _wape(np.concatenate(predicted), np.concatenate(actual))
        if error is not None and (best["wape"] is None or error < best["wape"]):
            best = {"method": method, "wape": error}
    return best


def _simple_forecast(context: np.ndarray, holdout: int, method: str, season: int) -> np.ndarray:
    average = np.nanmean(context)
    if method == "average":
        return np.full(holdout, average)
    repeated = context[-season:][np.arange(holdout) % season]
    return np.where(np.isfinite(repeated), repeated, average)


def _wape(predicted: np.ndarray, actual: np.ndarray) -> float | None:
    observed = np.isfinite(actual) & np.isfinite(predicted)
    scale = float(np.abs(actual[observed]).sum())
    if scale == 0:
        return None
    return float(np.abs(actual[observed] - predicted[observed]).sum() / scale)


def backtest(
    forecaster: TimestralForecaster,
    values: np.ndarray,
    holdout: int,
    covariates: dict[str, np.ndarray],
    frequency: str,
) -> dict[str, Any]:
    """Forecasts held-out windows from what came before them and scores them together."""
    history = len(values)
    tested: list[dict[str, Any]] = []
    plain: list[dict[str, Any]] = []
    actuals: list[np.ndarray] = []
    cuts: list[int] = []
    for cut in window_cuts(history, holdout):
        end = history - cut
        first = max(0, end - MAX_TEST_CONTEXT)
        try:
            with_all = run_one(
                forecaster, values[first:end], holdout, window(covariates, first, end, holdout)
            )
            without = run_one(forecaster, values[first:end], holdout, {}) if covariates else None
        except ValueError:
            # An earlier stretch can be unusable when the full history isn't, such as all gaps.
            if not cuts:
                raise
            break
        tested.append(with_all)
        if without:
            plain.append(without)
        actuals.append(values[end : end + holdout])
        cuts.append(cut)
    scored = score(tested, actuals)
    baseline = score(plain, actuals) if plain else None
    return {
        "holdout": holdout,
        "starting_points": len(cuts),
        "tested_points": count_tested_points(values, holdout, cuts),
        "forecast": scored,
        "baseline": baseline,
        "simple": simple_benchmark(values, holdout, cuts, frequency),
        "quantile_loss_change": _change(scored, baseline),
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
    baseline = run_one(forecaster, values, horizon, {}) if covariates else None
    tested = backtest(forecaster, values, holdout, covariates, request["frequency"])
    for series in (main, baseline):
        if series:
            del series["quantiles"], series["levels"]
    return {
        "forecast": main,
        "baseline": baseline,
        "backtest": tested,
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
