# apps/data-science/datascience/forecast.py

"""The forecast operation: checks the request, then forecasts in an isolated child.

Runs in the driver, so it uses only the standard library. The series travels inline
in the arguments; the child reads it from request.json and writes result.json.
"""

import json
import math
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from driver.server import OperationContext, OperationError

CHILD_SCRIPT = Path(__file__).resolve().parent / "child_forecast.py"
MODEL_DIR = Path("/opt/models/timestral-123m")

FREQUENCIES = ("hourly", "daily", "weekly", "monthly")
HOLIDAY_REGIONS = ("uk", "eu", "us", "au")
TIMINGS = ("known_future", "past_only")
KINDS = ("number", "category")
# The model reads at most 32,768 steps of context and forecasts up to 1,024 per block.
MAX_HISTORY = 32_768
MAX_HORIZON = 1_024
MAX_COVARIATES = 8
MIN_HISTORY = 16
MAX_GAP_SHARE = 0.3
MAX_CATEGORY_CODE = 2**31
FIRST_YEAR, LAST_YEAR = 1950, 2100
ARGUMENT_KEYS = {"start", "frequency", "values", "horizon", "holiday_regions", "covariates"}
SERIES_KEYS = {"median", "low", "high"}


def validate_forecast(arguments: dict[str, Any]) -> dict[str, Any]:
    if set(arguments) != ARGUMENT_KEYS:
        raise _invalid("The forecast request has the wrong fields.")
    frequency = _choice(arguments["frequency"], FREQUENCIES, "frequency")
    values = _numbers(arguments["values"], "values", MAX_HISTORY)
    horizon = arguments["horizon"]
    if type(horizon) is not int or not 1 <= horizon <= MAX_HORIZON:
        raise _invalid(f"horizon must be between 1 and {MAX_HORIZON}.")
    if len(values) < max(MIN_HISTORY, 2 * horizon):
        raise _invalid("The history must be at least 16 points and twice the horizon.")
    if sum(value is None for value in values) > MAX_GAP_SHARE * len(values):
        raise _invalid("More than 30% of the history is missing.")
    start = _start(arguments["start"], frequency, len(values) + horizon)
    regions = arguments["holiday_regions"]
    if (
        not isinstance(regions, list)
        or len(set(regions)) != len(regions)
        or len(regions) > len(HOLIDAY_REGIONS)
    ):
        raise _invalid("holiday_regions must list each region at most once.")
    covariates = arguments["covariates"]
    if not isinstance(covariates, list) or len(covariates) > MAX_COVARIATES:
        raise _invalid(f"Up to {MAX_COVARIATES} covariates are allowed.")
    return {
        "start": start,
        "frequency": frequency,
        "values": values,
        "horizon": horizon,
        "holiday_regions": [_choice(region, HOLIDAY_REGIONS, "region") for region in regions],
        "covariates": [_covariate(item, len(values), horizon) for item in covariates],
    }


def run_forecast(context: OperationContext, arguments: dict[str, Any]) -> dict[str, Any]:
    request = {**arguments, "model_dir": str(MODEL_DIR)}
    (context.workdir / "request.json").write_text(json.dumps(request))
    child = context.run([sys.executable, "-I", str(CHILD_SCRIPT)])
    if child.returncode != 0:
        if child.signal is not None or "MemoryError" in child.stderr_tail:
            raise OperationError("resource_limit", "The forecast exceeded the service's limits.")
        raise OperationError("forecast_failed", "The forecast couldn't be computed.")
    try:
        result = json.loads((context.workdir / "result.json").read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise OperationError("forecast_failed", "The forecast couldn't be computed.") from exc
    if isinstance(result, dict) and "error" in result:
        raise OperationError("invalid_series", "This series can't be forecast.")
    if not _well_formed(result, arguments):
        raise OperationError("forecast_failed", "The forecast couldn't be computed.")
    return result


def _invalid(message: str) -> OperationError:
    return OperationError("invalid_request", message)


def _choice(value: Any, choices: tuple[str, ...], name: str) -> str:
    if value not in choices:
        raise _invalid(f"{name} must be one of {', '.join(choices)}.")
    return value


def _numbers(value: Any, name: str, limit: int, *, integral: bool = False) -> list[float | None]:
    if not isinstance(value, list) or not 1 <= len(value) <= limit:
        raise _invalid(f"{name} must be a list of up to {limit} numbers.")
    for item in value:
        if item is None:
            continue
        if type(item) not in {int, float} or not math.isfinite(item):
            raise _invalid(f"{name} must hold finite numbers or null.")
        if integral and (item != int(item) or abs(item) > MAX_CATEGORY_CODE):
            raise _invalid(f"{name} must hold whole-number category codes.")
    return value


def _start(value: Any, frequency: str, periods: int) -> str:
    """Normalises the first period's start and checks every period fits the calendars."""
    if not isinstance(value, str) or len(value) > 32:
        raise _invalid("start must be an ISO date.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise _invalid("start must be an ISO date.") from exc
    if parsed.tzinfo is not None:
        raise _invalid("start must not carry a time zone.")
    if frequency != "hourly" and parsed.time() != datetime.min.time():
        raise _invalid("start must be a date for this frequency.")
    if frequency == "monthly" and parsed.day != 1:
        raise _invalid("start must be the first of a month for monthly series.")
    days = {"hourly": periods / 24, "daily": periods, "weekly": periods * 7}.get(
        frequency, periods * 31
    )
    if parsed.year < FIRST_YEAR or parsed.year + math.ceil(days / 365) > LAST_YEAR:
        raise _invalid(f"The series must fall between {FIRST_YEAR} and {LAST_YEAR}.")
    if frequency == "hourly":
        return parsed.isoformat(timespec="seconds")
    return date(parsed.year, parsed.month, parsed.day).isoformat()


def _covariate(value: Any, history: int, horizon: int) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"timing", "kind", "values"}:
        raise _invalid("A covariate has the wrong fields.")
    timing = _choice(value["timing"], TIMINGS, "timing")
    kind = _choice(value["kind"], KINDS, "kind")
    expected = history + horizon if timing == "known_future" else history
    values = _numbers(value["values"], "covariate values", expected, integral=kind == "category")
    if len(values) != expected:
        raise _invalid(
            "Known-future covariates must cover the history and the horizon; "
            "past-only covariates must cover the history."
        )
    return {"timing": timing, "kind": kind, "values": values}


def _well_formed(result: Any, arguments: dict[str, Any]) -> bool:
    """Checks the child's result has every series at the lengths the request implies."""
    if not isinstance(result, dict):
        return False
    horizon = arguments["horizon"]
    backtest = result.get("backtest")
    if not isinstance(backtest, dict) or type(backtest.get("holdout")) is not int:
        return False
    holdout = backtest["holdout"]
    shares = result.get("holiday_covariates")
    return (
        _series(result.get("forecast"), horizon)
        and (result.get("baseline") is None or _series(result["baseline"], horizon))
        and _series(backtest.get("forecast"), holdout)
        and (backtest.get("baseline") is None or _series(backtest["baseline"], holdout))
        and isinstance(shares, dict)
        and set(shares) == set(arguments["holiday_regions"])
        and all(_finite_list(row, len(arguments["values"]) + horizon) for row in shares.values())
        and isinstance(result.get("holidays"), list)
    )


def _series(value: Any, length: int) -> bool:
    return (
        isinstance(value, dict)
        and set(value) >= SERIES_KEYS
        and all(_finite_list(value[key], length) for key in SERIES_KEYS)
    )


def _finite_list(value: Any, length: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) == length
        and all(type(item) in {int, float} and math.isfinite(item) for item in value)
    )
