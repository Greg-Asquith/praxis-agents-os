# apps/api/services/data_science/run_forecast.py

"""Runs one forecast on the isolated data science service."""

from pydantic import ValidationError

from core.settings import settings
from services.data_science.domain import (
    DataScienceError,
    ServiceForecastRequest,
    ServiceForecastResult,
    ServiceSeries,
)
from utils.isolated_service import IsolatedService, post_isolated_operation

# The service's budget covers the forecast; this covers cold start and the round trip.
REQUEST_ALLOWANCE_SECONDS = 60
INVALID_RESPONSE_MESSAGE = "The data science service gave an invalid answer."


async def run_forecast(request: ServiceForecastRequest) -> ServiceForecastResult:
    """Sends one forecast inline and returns its result once every series fits the request."""
    if not settings.data_science_available:
        raise DataScienceError("unavailable", "The data science service isn't available.")
    service = IsolatedService(
        label="data science service",
        url=str(settings.DATA_SCIENCE_URL),
        auth=settings.DATA_SCIENCE_AUTH,
        shared_secret=settings.DATA_SCIENCE_SHARED_SECRET,
        error=DataScienceError,
    )
    payload = {
        "operation": "forecast",
        "timeout_seconds": settings.DATA_SCIENCE_TIMEOUT_SECONDS,
        "inputs": [],
        "outputs": [],
        "arguments": request.model_dump(mode="json"),
    }
    body = await post_isolated_operation(
        service,
        payload,
        request_seconds=settings.DATA_SCIENCE_TIMEOUT_SECONDS + REQUEST_ALLOWANCE_SECONDS,
    )
    try:
        result = ServiceForecastResult.model_validate(body.get("result"))
    except ValidationError as exc:
        raise DataScienceError("invalid_response", INVALID_RESPONSE_MESSAGE) from exc
    if not _fits(result, request):
        raise DataScienceError("invalid_response", INVALID_RESPONSE_MESSAGE)
    return result


def _fits(result: ServiceForecastResult, request: ServiceForecastRequest) -> bool:
    horizon, history = request.horizon, len(request.values)
    with_covariates = bool(request.holiday_regions or request.covariates)
    return (
        _series_fits(result.forecast, horizon)
        and (result.baseline is not None) == with_covariates
        and (result.baseline is None or _series_fits(result.baseline, horizon))
        and result.backtest.holdout <= min(horizon, history // 4)
        and (result.backtest.baseline is not None) == with_covariates
        and set(result.holiday_covariates) == set(request.holiday_regions)
        and all(len(row) == history + horizon for row in result.holiday_covariates.values())
    )


def _series_fits(series: ServiceSeries, length: int) -> bool:
    return len(series.median) == len(series.low) == len(series.high) == length
