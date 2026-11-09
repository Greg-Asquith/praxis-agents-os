# apps/api/services/data_science/domain.py

"""Typed data science service requests and results.

Arguments are numbers and names from fixed lists, which the service checks against its
own. Covariate names and category labels stay in the API; the service sees only numbers.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from utils.isolated_service import IsolatedServiceError

Frequency = Literal["hourly", "daily", "weekly", "monthly"]
HolidayRegion = Literal["uk", "eu", "us", "au"]
CovariateTiming = Literal["known_future", "past_only"]
CovariateKind = Literal["number", "category"]
SimpleMethod = Literal["average", "same_period_last_cycle"]

# Mirrors apps/data-science/datascience/forecast.py.
MIN_HISTORY = 16
MAX_GAP_SHARE = 0.3

FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]


class DataScienceError(IsolatedServiceError):
    """A data science service failure with a stable code and a message safe to show an agent."""


class ServiceCovariate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timing: CovariateTiming
    kind: CovariateKind
    values: list[FiniteFloat | None]


class ServiceForecastRequest(BaseModel):
    """The forecast operation's arguments, exactly as the service accepts them."""

    model_config = ConfigDict(extra="forbid")

    start: str
    frequency: Frequency
    values: list[FiniteFloat | None]
    horizon: int
    holiday_regions: list[HolidayRegion]
    covariates: list[ServiceCovariate]


class ServiceSeries(BaseModel):
    model_config = ConfigDict(extra="ignore")

    median: list[FiniteFloat]
    low: list[FiniteFloat]
    high: list[FiniteFloat]


class ServiceScore(BaseModel):
    """Backtest metrics pooled over every test window."""

    model_config = ConfigDict(extra="forbid")

    wape: FiniteFloat | None
    coverage: FiniteFloat | None
    quantile_loss: FiniteFloat | None


class ServiceSimpleBenchmark(BaseModel):
    """The better of the two simple forecasts over the same test windows."""

    model_config = ConfigDict(extra="forbid")

    method: SimpleMethod
    wape: FiniteFloat | None


class ServiceBacktest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    holdout: int = Field(ge=1)
    starting_points: int = Field(ge=1)
    tested_points: int = Field(ge=0)
    forecast: ServiceScore
    baseline: ServiceScore | None
    simple: ServiceSimpleBenchmark
    quantile_loss_change: FiniteFloat | None


class ServiceHoliday(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str = Field(max_length=10)
    region: HolidayRegion
    name: str = Field(max_length=200)
    share: FiniteFloat = Field(ge=0, le=1)


class ServiceForecastResult(BaseModel):
    """The forecast operation's result; `run_forecast` checks every length against the request."""

    model_config = ConfigDict(extra="forbid")

    forecast: ServiceSeries
    baseline: ServiceSeries | None
    backtest: ServiceBacktest
    holiday_covariates: dict[HolidayRegion, list[FiniteFloat]]
    holidays: list[ServiceHoliday] = Field(max_length=10_000)
