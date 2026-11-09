# apps/api/tests/scenarios/test_forecasting.py

"""forecast_series called from a run_code script through the production runtime."""

import importlib
import json

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.settings import settings
from services.agents.runtime.tools.code_mode import RUN_CODE_TOOL_NAME
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)

# The package exports a function with the module's name.
run_forecast_module = importlib.import_module("services.data_science.run_forecast")

SCRIPT = """
values = [100 + (day % 7) * 10 for day in range(28)]
result = await forecast_series(
    title='Daily Orders', start='2026-01-05', frequency='daily', values=values, horizon=7
)
result['forecast'][0]['median']
"""


def _series(length: int) -> dict:
    return {"median": [130.4] * length, "low": [120.0] * length, "high": [140.0] * length}


async def test_script_forecast_is_audited_and_keeps_the_chart_from_the_model(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "DATA_SCIENCE_URL", "http://data-science.test")
    monkeypatch.setattr(settings, "DATA_SCIENCE_AUTH", "none")

    async def post(_service, payload, *, request_seconds):
        tested = {"wape": 0.05, "coverage": 0.86, "quantile_loss": 0.04}
        return {
            "ok": True,
            "result": {
                "forecast": _series(7),
                "baseline": None,
                "backtest": {
                    "holdout": 7,
                    "starting_points": 3,
                    "tested_points": 21,
                    "forecast": tested,
                    "baseline": None,
                    "simple": {"method": "average", "wape": 0.2},
                    "quantile_loss_change": None,
                },
                "holiday_covariates": {},
                "holidays": [],
            },
        }

    monkeypatch.setattr(run_forecast_module, "post_isolated_operation", post)
    seen_requests = []
    context = await build_scenario_agent(db_session_factory, tool_names=[])

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn((ToolCall(RUN_CODE_TOOL_NAME, {"code": SCRIPT}, "forecast-script"),)),
                "Expect about 130 orders a day.",
            ],
            seen_requests=seen_requests,
        ),
    )

    assert result.output == "Expect about 130 orders a day."
    [nested] = [
        row
        for row in result.audit_rows
        if row.details.get("parent_tool_call_id") == "forecast-script"
    ]
    assert nested.tool_name == "forecast_series"
    # Metadata carries the chart to the transcript; only content reaches the model.
    model_context = json.dumps(
        [
            str(getattr(part, "content", ""))
            for message in seen_requests[-1][0]
            for part in message.parts
        ]
    )
    assert "130" in model_context
    # Only the chart lists history periods; the script names just the first.
    assert "2026-01-06" not in model_context
