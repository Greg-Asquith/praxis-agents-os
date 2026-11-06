# apps/api/services/agents/runtime/tools/forecasting.py

"""Runtime tool that forecasts a time series on the isolated data science service."""

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
    ServiceSeries,
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
    """How the method did on the end of the history, forecast from what came before it."""

    model_config = ConfigDict(extra="forbid")

    periods: int
    typical_error: float | None = Field(description="Mean absolute error over total actuals.")
    range_coverage: float | None = Field(description="Share of actuals inside the low-high range.")
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


class ChartBacktest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    forecast: ChartSeries
    baseline: ChartSeries | None


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
    caveat: str | None
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
        "likely low-high range (10th to 90th percentile), a backtest on the end of the "
        "history, and public holidays in the horizon. Pass real history in order, one "
        "value per period from start, with null for a gap; never invent or fill in "
        "history. holiday_regions adds public holiday calendars as covariates. Put events "
        "known in advance, such as promos, planned spend, or price changes, in known_future "
        "covariates; retail events such as Black Friday aren't public holidays. This is a "
        "forecast, not a what-if or cause-and-effect estimate. When reporting, give the "
        "range and the backtest's typical error, not only the median."
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
    return value if isinstance(value, str) else format(value, "g")


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
    tested = result.backtest.forecast
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
                periods[history:],
                result.forecast.median,
                result.forecast.low,
                result.forecast.high,
                strict=True,
            )
        ],
        backtest=ForecastBacktest(
            periods=result.backtest.holdout,
            typical_error=_rounded(tested.wape),
            range_coverage=_rounded(tested.coverage),
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
        caveat=SHORT_HISTORY_CAVEAT if history < 3 * request.horizon else None,
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
            forecast=series(result.backtest.forecast),
            baseline=series(result.backtest.baseline),
        ),
        covariates=[*holiday_rows, *provided_rows],
    )


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 3)
