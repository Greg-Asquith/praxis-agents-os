# apps/api/services/agents/runtime/tools/forecasting.py

"""Runtime tool that forecasts a time series on the isolated data science service."""

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import ModelRetry, ToolReturn
from pydantic_ai.exceptions import ToolFailed

from core.settings import settings
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.agents.runtime.tools.registry import runtime_tool
from services.data_science import run_forecast
from services.data_science.domain import (
    MAX_GAP_SHARE,
    MIN_HISTORY,
    CovariateKind,
    CovariateTiming,
    DataScienceError,
    FiniteFloat,
    Frequency,
    HolidayRegion,
    ServiceCovariate,
    ServiceForecastRequest,
    ServiceForecastResult,
    ServiceScore,
    ServiceSeries,
    ServiceSimpleBenchmark,
    SimpleMethod,
)
from services.data_science.run_forecast import REQUEST_ALLOWANCE_SECONDS
from services.data_science.utils import input_decimals, period_labels

METHOD = "Timestral 123M"
HOLIDAY_NAMES: dict[HolidayRegion, str] = {
    "uk": "UK Holidays",
    "eu": "EU Holidays",
    "us": "US Holidays",
    "au": "Australia Holidays",
}
# The card shows the end of the history: three horizons, or at least 90 periods.
CHART_HORIZONS = 3
CHART_MIN_HISTORY = 90
# Worst case: 3,072 history and 1,024 forecast periods, every series, twelve covariates.
MAX_PUBLIC_RESULT_CHARS = 1_000_000
SHORT_HISTORY_CAVEAT = (
    "The history is less than three times the horizon, so treat the range as rough."
)
# A forecast must beat a simple one by more than chance to count as adding anything.
NO_BETTER_SHARE = 0.95
HIGH_ERROR = 0.3
VERY_HIGH_ERROR = 0.5
LOW_COVERAGE = 0.6
MIN_TESTED_POINTS = 8
# Small changes in test error are noise, so covariates stay unless they clearly hurt.
COVARIATE_HARM = 0.02
# About 28 per period: below that, chance alone moves a whole-number count by over 15%.
NOISY_COUNT_ERROR = 0.15
PERIOD_NAMES: dict[Frequency, str] = {
    "hourly": "hour",
    "daily": "day",
    "weekly": "week",
    "monthly": "month",
}
SIMPLE_METHOD_NAMES: dict[SimpleMethod, str] = {
    "average": "the average of past values",
    "same_period_last_cycle": "repeating the same period from the last cycle",
}
# Daily is absent: the minimum history already covers two weeks.
TWO_CYCLES: dict[Frequency, tuple[int, str]] = {
    "hourly": (48, "days"),
    "weekly": (104, "years"),
    "monthly": (24, "years"),
}
Reliability = Literal["good", "limited", "low"]
# Travels with the result: a model can hold one without having read the description or skill.
HOW_TO_REPORT: dict[Reliability, str] = {
    "good": "Give the range and the typical error, not only the median.",
    "limited": "Give the range and the typical error, and tell the person every caveat.",
    "low": (
        "Start by saying not to rely on this forecast alone. Then give the figure as the usual "
        "level with its range, the typical error beside the simple forecast's error, and every "
        "caveat."
    ),
}
CovariateValue = FiniteFloat | Annotated[str, Field(max_length=80)] | None


class ForecastCovariate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80, description="Short name, such as Promo Days.")
    timing: CovariateTiming = Field(
        description=(
            "known_future: values cover the history and then the horizon, such as planned "
            "promos or spend. past_only: values cover the history only."
        )
    )
    kind: CovariateKind = Field(
        default="number",
        description="number, or category for labels such as store format or campaign type.",
    )
    values: list[CovariateValue] = Field(
        description="One value per period in order; null for unknown. Labels for a category."
    )


class ForecastRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period: str
    median: float
    low: float
    high: float


class ForecastBacktest(BaseModel):
    """How the method did near the end of the history, forecast from what came before it."""

    model_config = ConfigDict(extra="forbid")

    periods: int = Field(description="Periods forecast ahead in each test.")
    starting_points: int = Field(description="How many points in the history were tested from.")
    tested_points: int = Field(description="Periods with an actual value scored across every test.")
    typical_error: float | None = Field(description="Mean absolute error over total actuals.")
    range_coverage: float | None = Field(description="Share of actuals inside the low-high range.")
    simple_method: SimpleMethod = Field(description="The simple forecast compared against.")
    simple_error: float | None = Field(description="That simple forecast's typical error.")
    covariate_error_change: float | None = Field(
        description="Relative change in error from adding covariates; negative is better."
    )


class ForecastHoliday(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str
    region: HolidayRegion
    name: str
    share: float = Field(description="Share of the region's population on holiday.")


class ChartSeries(BaseModel):
    model_config = ConfigDict(extra="forbid")

    median: list[float]
    low: list[float]
    high: list[float]


class ChartScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    typical_error: float | None
    range_coverage: float | None


class ChartBacktest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    forecast: ChartScore
    baseline: ChartScore | None


class ChartCovariate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    source: Literal["holiday", "provided"]
    timing: CovariateTiming
    kind: CovariateKind
    values: list[float | None]
    labels: list[str] | None = None


class ForecastChart(BaseModel):
    """Presenter data: the end of the history, both forecasts, the backtest, and covariates."""

    model_config = ConfigDict(extra="forbid")

    periods: list[str]
    history: list[float | None]
    forecast: ChartSeries
    baseline: ChartSeries | None
    backtest: ChartBacktest
    covariates: list[ChartCovariate]


class ForecastResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    unit: str | None
    frequency: Frequency
    method: str
    history_points: int
    forecast: list[ForecastRow]
    backtest: ForecastBacktest
    holidays: list[ForecastHoliday]
    covariates_used: bool = Field(
        description="False when there are none, or when they made the test less accurate."
    )
    reliability: Reliability = Field(description="How far the tests say to trust this forecast.")
    caveats: list[str] = Field(description="Plain warnings to pass on, most serious first.")
    how_to_report: str = Field(description="What an answer based on this forecast must include.")
    chart: ForecastChart | None = None


def forecast_series_available() -> bool:
    return settings.data_science_available


@runtime_tool(
    name="forecast_series",
    provider="core",
    label="Forecast Series",
    code_eligible=True,
    description=(
        "Forecast a time series with Timestral 123M and return each period's median and "
        "likely low-high range (10th to 90th percentile), a backtest from several points "
        "near the end of the history, a reliability rating with caveats, and public holidays "
        "in the horizon. Pass real history in order, one "
        "value per period from start, with null for a gap; never invent or fill in "
        "history. holiday_regions adds public holiday calendars as covariates. Put events "
        "known in advance, such as promos, planned spend, or price changes, in known_future "
        "covariates; retail events such as Black Friday aren't public holidays. This is a "
        "forecast, not a what-if or cause-and-effect estimate. Even in a short answer, always "
        "give the range, the backtest's typical error, the simple forecast's error, the "
        "reliability, and every caveat, not only the median. When reliability is low, say "
        "so first and present the figure as the usual level, not a prediction of changes."
    ),
    effect=TOOL_EFFECT_READ,
    supports_approval=False,
    timeout=settings.DATA_SCIENCE_TIMEOUT_SECONDS + REQUEST_ALLOWANCE_SECONDS,
    output_model=ForecastResult,
    max_public_result_chars=MAX_PUBLIC_RESULT_CHARS,
    preview_list_path="forecast",
    configurable=False,
    auto_mount=True,
    availability_check=forecast_series_available,
    presentation=ToolPresentation(
        icon="chart",
        running_label="Forecasting",
        completed_label="Forecast {title}",
        failed_label="Couldn't Forecast",
        arg_fields=(
            ToolFieldPresentation(key="frequency", label="Frequency"),
            ToolFieldPresentation(key="horizon", label="Horizon", format="number"),
        ),
    ),
)
async def forecast_series(
    title: Annotated[str, Field(min_length=1, max_length=120, description="What is forecast.")],
    start: Annotated[
        str,
        Field(
            max_length=32,
            description=(
                "First period's ISO date, such as 2025-01-06; a date and hour for hourly; the "
                "first of the month for monthly."
            ),
        ),
    ],
    frequency: Frequency,
    values: Annotated[
        list[FiniteFloat | None],
        Field(min_length=1, description="The history, one value per period; null for a gap."),
    ],
    horizon: Annotated[int, Field(ge=1, description="Periods to forecast after the history.")],
    unit: Annotated[
        str | None, Field(max_length=40, description="Optional unit, such as orders or GBP.")
    ] = None,
    holiday_regions: Annotated[
        list[HolidayRegion] | None,
        Field(max_length=4, description="Public holiday calendars to allow for: uk, eu, us, au."),
    ] = None,
    covariates: Annotated[
        list[ForecastCovariate] | None,
        Field(description="Other series that help explain the history."),
    ] = None,
) -> ToolReturn:
    """Forecasts one series and keeps the presenter's series out of the model's result."""
    holiday_regions = holiday_regions or []
    covariates = covariates or []
    _check_series(values, horizon, holiday_regions, covariates)
    labels = [_category_labels(item) for item in covariates]
    request = ServiceForecastRequest(
        start=start,
        frequency=frequency,
        values=values,
        horizon=horizon,
        holiday_regions=holiday_regions,
        covariates=[
            ServiceCovariate(
                timing=item.timing,
                kind=item.kind,
                values=_coded(item, item_labels),
            )
            for item, item_labels in zip(covariates, labels, strict=True)
        ],
    )
    try:
        result = await run_forecast(request)
    except DataScienceError as exc:
        if exc.code == "invalid_request":
            raise ModelRetry(exc.message) from exc
        if exc.code == "invalid_series":
            raise ToolFailed(
                "Timestral couldn't forecast this series. Check it isn't mostly gaps or one "
                "repeated value."
            ) from exc
        raise ToolFailed(exc.message) from exc
    forecast = _forecast_result(request, result, title=title, unit=unit)
    chart = _chart(request, result, covariates, labels)
    public = forecast.model_copy(update={"chart": chart}).model_dump(mode="json")
    return ToolReturn(
        return_value=forecast.model_dump(mode="json", exclude={"chart"}),
        metadata={"public_result": public},
    )


def _check_series(
    values: list[float | None],
    horizon: int,
    holiday_regions: list[HolidayRegion],
    covariates: list[ForecastCovariate],
) -> None:
    history = len(values)
    if history > settings.FORECAST_MAX_HISTORY_POINTS:
        raise ModelRetry(
            f"Send at most {settings.FORECAST_MAX_HISTORY_POINTS} history points; use a coarser "
            "frequency or the most recent history."
        )
    if horizon > settings.FORECAST_MAX_HORIZON:
        raise ModelRetry(f"horizon must be at most {settings.FORECAST_MAX_HORIZON} periods.")
    if history < max(MIN_HISTORY, 2 * horizon):
        raise ModelRetry(
            f"A {horizon}-period forecast needs at least {max(MIN_HISTORY, 2 * horizon)} periods "
            f"of history, and there are {history}. Shorten the horizon or say the history is "
            "too short to forecast."
        )
    if sum(value is None for value in values) > MAX_GAP_SHARE * history:
        raise ModelRetry("More than 30% of the history is missing, so it can't be forecast.")
    if len(set(holiday_regions)) != len(holiday_regions):
        raise ModelRetry("List each holiday region once.")
    if len(covariates) > settings.FORECAST_MAX_COVARIATES:
        raise ModelRetry(f"Send at most {settings.FORECAST_MAX_COVARIATES} covariates.")
    for item in covariates:
        expected = history + horizon if item.timing == "known_future" else history
        if len(item.values) != expected:
            raise ModelRetry(
                f"Covariate {item.name!r} has {len(item.values)} values but needs {expected}: "
                "known_future covers the history and the horizon, past_only the history."
            )
        if item.kind == "number" and any(isinstance(value, str) for value in item.values):
            raise ModelRetry(f"Covariate {item.name!r} is a number but holds text.")


def _category_labels(item: ForecastCovariate) -> list[str] | None:
    if item.kind != "category":
        return None
    seen: dict[str, None] = {}
    for value in item.values:
        if value is not None:
            seen.setdefault(_label(value), None)
    return list(seen)


def _coded(item: ForecastCovariate, labels: list[str] | None) -> list[float | None]:
    if labels is None:
        # _check_series has refused text in a number covariate.
        return [None if value is None else float(value) for value in item.values]
    codes = {label: index for index, label in enumerate(labels)}
    return [None if value is None else codes[_label(value)] for value in item.values]


def _label(value: float | str) -> str:
    if isinstance(value, str):
        return value
    # Keep every digit so long numeric IDs stay distinct.
    return str(int(value)) if float(value).is_integer() else repr(value)


def _forecast_result(
    request: ServiceForecastRequest,
    result: ServiceForecastResult,
    *,
    title: str,
    unit: str | None,
) -> ForecastResult:
    history = len(request.values)
    decimals = input_decimals(request.values)
    periods = period_labels(request.start, request.frequency, history + request.horizon)
    use_covariates = _covariates_used(result)
    chosen = result.forecast if use_covariates or result.baseline is None else result.baseline
    tested = result.backtest.forecast
    if result.backtest.baseline is not None and not use_covariates:
        tested = result.backtest.baseline
    reliability, caveats = _assessment(request, result, tested)
    if result.baseline is not None and not use_covariates:
        caveats.append(_left_out_caveat(result, decimals))
    return ForecastResult(
        title=title,
        unit=unit,
        frequency=request.frequency,
        method=METHOD,
        history_points=history,
        forecast=[
            ForecastRow(
                period=period,
                median=round(median, decimals),
                low=round(low, decimals),
                high=round(high, decimals),
            )
            for period, median, low, high in zip(
                periods[history:], chosen.median, chosen.low, chosen.high, strict=True
            )
        ],
        backtest=ForecastBacktest(
            periods=result.backtest.holdout,
            starting_points=result.backtest.starting_points,
            tested_points=result.backtest.tested_points,
            typical_error=_rounded(tested.wape),
            range_coverage=_rounded(tested.coverage),
            simple_method=result.backtest.simple.method,
            simple_error=_rounded(result.backtest.simple.wape),
            covariate_error_change=_rounded(result.backtest.quantile_loss_change),
        ),
        holidays=[
            ForecastHoliday(
                date=holiday.date,
                region=holiday.region,
                name=holiday.name,
                share=round(holiday.share, 2),
            )
            for holiday in result.holidays
        ],
        covariates_used=use_covariates,
        reliability=reliability,
        caveats=caveats,
        how_to_report=HOW_TO_REPORT[reliability],
    )


def _covariates_used(result: ServiceForecastResult) -> bool:
    if result.baseline is None:
        return False
    change = result.backtest.quantile_loss_change
    return change is None or change <= COVARIATE_HARM


def _assessment(
    request: ServiceForecastRequest, result: ServiceForecastResult, tested: ServiceScore
) -> tuple[Reliability, list[str]]:
    """Rates the forecast from its tests and the data, with the reasons in plain words."""
    serious = _test_failures(tested, result.backtest.simple)
    limits = _test_limits(tested, result.backtest.tested_points, flagged=bool(serious))
    limits += _data_limits(request)
    reliability: Reliability = "low" if serious else "limited" if limits else "good"
    return reliability, [*serious, *limits]


def _test_failures(tested: ServiceScore, simple: ServiceSimpleBenchmark) -> list[str]:
    error = tested.wape
    if error is None:
        return ["This forecast couldn't be tested, because the tested periods have no values."]
    failures = []
    if simple.wape is not None and error >= NO_BETTER_SHARE * simple.wape:
        failures.append(
            f"In testing, this forecast was typically off by {error:.0%}, and "
            f"{SIMPLE_METHOD_NAMES[simple.method]} was off by {simple.wape:.0%}. Treat it as a "
            "guide to the usual level, not a prediction of changes."
        )
    if error > VERY_HIGH_ERROR:
        failures.append(
            f"In testing, this forecast was typically off by {error:.0%}, so use it only as a "
            "rough guide."
        )
    return failures


def _test_limits(tested: ServiceScore, tested_points: int, *, flagged: bool) -> list[str]:
    limits = []
    error, coverage = tested.wape, tested.coverage
    if not flagged and error is not None and error > HIGH_ERROR:
        limits.append(f"In testing, this forecast was typically off by {error:.0%}.")
    if tested_points < MIN_TESTED_POINTS:
        limits.append(
            f"The test covered only {tested_points} periods, so its accuracy figures are rough."
        )
    elif coverage is not None and coverage < LOW_COVERAGE:
        limits.append(
            f"Only {coverage:.0%} of actual values fell inside the likely range in testing, so "
            "expect more variation than the range shows."
        )
    return limits


def _data_limits(request: ServiceForecastRequest) -> list[str]:
    history = len(request.values)
    limits = []
    if history < 3 * request.horizon:
        limits.append(SHORT_HISTORY_CAVEAT)
    cycle = TWO_CYCLES.get(request.frequency)
    if cycle and history < cycle[0]:
        limits.append(
            f"The history covers less than two {cycle[1]}, so a repeating seasonal pattern "
            "can't be told apart from chance."
        )
    noisy = _noisy_count_caveat(request)
    if noisy:
        limits.append(noisy)
    return limits


def _noisy_count_caveat(request: ServiceForecastRequest) -> str | None:
    """Warns when counts are so small that chance alone limits any forecast's accuracy."""
    observed = [value for value in request.values if value is not None]
    if not observed or any(value < 0 or not value.is_integer() for value in observed):
        return None
    mean = sum(observed) / len(observed)
    if mean == 0:
        return None
    # A random count's typical distance from its mean, as a share of the mean.
    chance_error = min(1.0, math.sqrt(2 / (math.pi * mean)))
    if chance_error < NOISY_COUNT_ERROR:
        return None
    name = PERIOD_NAMES[request.frequency]
    advice = "" if request.frequency == "monthly" else " Monthly totals give steadier figures."
    return (
        f"These are small counts, about {mean:.2g} per {name}, so chance alone moves each "
        f"{name} by about {chance_error:.0%}.{advice}"
    )


def _left_out_caveat(result: ServiceForecastResult, decimals: int) -> str:
    change = result.backtest.quantile_loss_change or 0
    places = decimals + 1
    with_all = round(sum(result.forecast.median) / len(result.forecast.median), places)
    without = round(sum(result.baseline.median) / len(result.baseline.median), places)
    return (
        f"Adding holidays and other data made the test {change:.0%} less accurate, so this "
        f"forecast leaves them out. It averages {without} per period, or {with_all} with them."
    )


def _chart(
    request: ServiceForecastRequest,
    result: ServiceForecastResult,
    covariates: list[ForecastCovariate],
    labels: list[list[str] | None],
) -> ForecastChart:
    history, horizon = len(request.values), request.horizon
    shown = min(history, max(CHART_HORIZONS * horizon, CHART_MIN_HISTORY))
    first = history - shown
    decimals = input_decimals(request.values)
    periods = period_labels(request.start, request.frequency, history + horizon)

    def series(values: ServiceSeries | None) -> ChartSeries | None:
        if values is None:
            return None
        return ChartSeries(
            median=[round(value, decimals) for value in values.median],
            low=[round(value, decimals) for value in values.low],
            high=[round(value, decimals) for value in values.high],
        )

    holiday_rows = [
        ChartCovariate(
            name=HOLIDAY_NAMES[region],
            source="holiday",
            timing="known_future",
            kind="number",
            values=[round(value, 3) for value in result.holiday_covariates[region][first:]],
        )
        for region in request.holiday_regions
    ]
    provided_rows = [
        ChartCovariate(
            name=item.name,
            source="provided",
            timing=item.timing,
            kind=item.kind,
            values=sent.values[first:],
            labels=item_labels,
        )
        for item, sent, item_labels in zip(covariates, request.covariates, labels, strict=True)
    ]
    return ForecastChart(
        periods=periods[first:],
        history=[None if value is None else round(value, decimals) for value in request.values][
            first:
        ],
        forecast=series(result.forecast),
        baseline=series(result.baseline),
        backtest=ChartBacktest(
            forecast=_chart_score(result.backtest.forecast),
            baseline=_chart_score(result.backtest.baseline),
        ),
        covariates=[*holiday_rows, *provided_rows],
    )


def _chart_score(score: ServiceScore | None) -> ChartScore | None:
    if score is None:
        return None
    return ChartScore(typical_error=_rounded(score.wape), range_coverage=_rounded(score.coverage))


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 3)
