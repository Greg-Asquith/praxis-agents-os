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


def _service_result(
    *,
    history: int = len(HISTORY),
    horizon: int = HORIZON,
    wape: float = 0.0912,
    simple_wape: float = 0.2,
    coverage: float = 0.75,
    tested_points: int = 24,
    change: float = -0.3,
) -> dict:
    tested = {"wape": wape, "coverage": coverage, "quantile_loss": 0.07}
    return {
        "forecast": _series(horizon),
        "baseline": _series(horizon, 99.0),
        "backtest": {
            "holdout": min(horizon, history // 4),
            "starting_points": 6,
            "tested_points": tested_points,
            "forecast": tested,
            "baseline": {**tested, "wape": 0.15, "quantile_loss": 0.1},
            "simple": {"method": "average", "wape": simple_wape},
            "quantile_loss_change": change,
        },
        "holiday_covariates": {"uk": [0.0] * (history + horizon)},
        "holidays": [{"date": "2026-01-01", "region": "uk", "name": "New Year's Day", "share": 1}],
    }


async def _forecast(answers: list[dict], *, values: list | None = None, **result) -> dict:
    """Forecasts a series whose values and frequency avoid every data caveat by default."""
    values = HISTORY if values is None else values
    frequency = result.pop("frequency", "daily")
    answers.append(_service_result(history=len(values), **result))
    outcome = await forecast_series(
        title="Orders",
        start="2025-01-06",
        frequency=frequency,
        values=values,
        horizon=HORIZON,
        holiday_regions=["uk"],
    )
    return outcome.return_value


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
    promo = [1234567, 1234568, None, 1234568] * 11

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
    assert visible["covariates_used"] is True
    chart = result.metadata["public_result"]["chart"]
    assert len(chart["periods"]) == len(HISTORY) + HORIZON
    assert [row["name"] for row in chart["covariates"]] == ["UK Holidays", "Promo"]
    assert chart["covariates"][1]["labels"] == ["1234567", "1234568"]


async def test_covariates_that_hurt_the_test_are_left_out(service) -> None:
    _, answers = service

    visible = await _forecast(answers, change=0.044)

    assert visible["covariates_used"] is False
    assert visible["forecast"][0]["median"] == 99.0
    # The score must describe the forecast returned, not the one left out.
    assert visible["backtest"]["typical_error"] == 0.15
    assert any("105.12" in caveat and "99.0" in caveat for caveat in visible["caveats"])


async def test_forecast_no_better_than_a_simple_one_is_low_reliability(service) -> None:
    _, answers = service

    visible = await _forecast(answers, wape=0.354, simple_wape=0.344)

    assert visible["reliability"] == "low"
    assert "34%" in visible["caveats"][0]


async def test_forecast_clearly_beating_a_simple_one_stays_good(service) -> None:
    _, answers = service

    visible = await _forecast(answers, wape=0.1, simple_wape=0.11)

    assert visible["reliability"] == "good"
    assert visible["caveats"] == []


async def test_small_whole_number_counts_are_flagged(service) -> None:
    _, answers = service
    small = [11.0, 12.0, 4.0, 8.0] * 10

    visible = await _forecast(answers, values=small)

    assert visible["reliability"] == "limited"
    assert any("about 8.8 per day" in caveat for caveat in visible["caveats"])


async def test_small_decimal_values_are_not_treated_as_counts(service) -> None:
    _, answers = service

    visible = await _forecast(answers, values=[1.5, 2.25, 3.5, 1.75] * 10)

    assert not any("small counts" in caveat for caveat in visible["caveats"])


async def test_less_than_two_seasonal_cycles_is_flagged(service) -> None:
    _, answers = service
    year = [100.5] * 52

    visible = await _forecast(answers, values=year, frequency="weekly")

    assert visible["reliability"] == "limited"
    assert any("two years" in caveat for caveat in visible["caveats"])


async def test_too_few_tested_points_is_flagged_over_coverage(service) -> None:
    _, answers = service

    visible = await _forecast(answers, tested_points=4, coverage=0.25)

    assert visible["reliability"] == "limited"
    assert len(visible["caveats"]) == 1
    assert "only 4 periods" in visible["caveats"][0]


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
