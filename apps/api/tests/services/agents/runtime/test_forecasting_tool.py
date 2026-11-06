# apps/api/tests/services/agents/runtime/test_forecasting_tool.py

"""forecast_series against a stub data science transport."""

import importlib

import pytest
from pydantic_ai import ModelRetry
from pydantic_ai.exceptions import ToolFailed

from core.settings import settings
from services.agents.runtime.tools.forecasting import ForecastCovariate, forecast_series
from services.agents.runtime.tools.permissions import is_tool_allowed
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG

# The package exports a function with the module's name.
run_forecast_module = importlib.import_module("services.data_science.run_forecast")

HISTORY = [100.0, 120.5, None, 110.25] * 10
HORIZON = 4


def _series(length: int, value: float = 105.123456) -> dict:
    return {"median": [value] * length, "low": [value - 10] * length, "high": [value + 10] * length}


def _service_result(*, history: int = len(HISTORY), horizon: int = HORIZON) -> dict:
    holdout = min(horizon, history // 4)
    tested = {**_series(holdout), "wape": 0.0912, "coverage": 0.75, "quantile_loss": 0.07}
    return {
        "forecast": _series(horizon),
        "baseline": _series(horizon, 99.0),
        "backtest": {
            "holdout": holdout,
            "forecast": tested,
            "baseline": {**tested, "quantile_loss": 0.1},
            "quantile_loss_change": -0.3,
        },
        "holiday_covariates": {"uk": [0.0] * (history + horizon)},
        "holidays": [{"date": "2026-01-01", "region": "uk", "name": "New Year's Day", "share": 1}],
    }


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> tuple[list[dict], list[dict]]:
    """Answers each request with the queued result and records what was sent."""
    monkeypatch.setattr(settings, "DATA_SCIENCE_URL", "http://data-science.test")
    monkeypatch.setattr(settings, "DATA_SCIENCE_AUTH", "none")
    sent: list[dict] = []
    answers: list[dict] = []

    async def post(_service, payload, *, request_seconds):
        sent.append(payload)
        return {"ok": True, "result": answers.pop(0)}

    monkeypatch.setattr(run_forecast_module, "post_isolated_operation", post)
    return sent, answers


def test_tool_is_hidden_without_the_service(monkeypatch: pytest.MonkeyPatch) -> None:
    definition = RUNTIME_TOOL_CATALOG["forecast_series"]
    monkeypatch.setattr(settings, "DATA_SCIENCE_URL", None)
    assert is_tool_allowed(definition, workspace=None) is False
    monkeypatch.setattr(settings, "DATA_SCIENCE_URL", "http://data-science.test")
    assert is_tool_allowed(definition, workspace=None) is True


async def test_forecast_keeps_names_and_chart_out_of_the_service_and_model(service) -> None:
    sent, answers = service
    answers.append(_service_result())
    promo = ["none", "promo", None, "promo"] * 11

    result = await forecast_series(
        title="Weekly Orders",
        start="2025-01-06",
        frequency="weekly",
        values=HISTORY,
        horizon=HORIZON,
        holiday_regions=["uk"],
        covariates=[
            ForecastCovariate(name="Promo", timing="known_future", kind="category", values=promo)
        ],
    )

    arguments = sent[0]["arguments"]
    assert arguments["covariates"] == [
        {"timing": "known_future", "kind": "category", "values": [0, 1, None, 1] * 11}
    ]
    assert sent[0]["timeout_seconds"] == settings.DATA_SCIENCE_TIMEOUT_SECONDS
    visible = result.return_value
    assert "chart" not in visible
    # History has two decimals, so the forecast is rounded to two.
    assert visible["forecast"][0] == {
        "period": "2025-10-13",
        "median": 105.12,
        "low": 95.12,
        "high": 115.12,
    }
    assert visible["backtest"]["typical_error"] == 0.091
    chart = result.metadata["public_result"]["chart"]
    assert len(chart["periods"]) == len(HISTORY) + HORIZON
    assert [row["name"] for row in chart["covariates"]] == ["UK Holidays", "Promo"]
    assert chart["covariates"][1]["labels"] == ["none", "promo"]


async def test_known_future_covariate_must_cover_the_horizon(service) -> None:
    sent, _ = service
    with pytest.raises(ModelRetry, match="needs 44"):
        await forecast_series(
            title="Orders",
            start="2025-01-06",
            frequency="weekly",
            values=HISTORY,
            horizon=HORIZON,
            covariates=[ForecastCovariate(name="Spend", timing="known_future", values=[1.0] * 40)],
        )
    assert sent == []


async def test_malformed_service_result_is_refused(service) -> None:
    _, answers = service
    malformed = _service_result()
    malformed["forecast"]["median"] = malformed["forecast"]["median"][:-1]
    answers.append(malformed)

    with pytest.raises(ToolFailed, match="invalid answer"):
        await forecast_series(
            title="Orders",
            start="2025-01-06",
            frequency="weekly",
            values=HISTORY,
            horizon=HORIZON,
            holiday_regions=["uk"],
        )
