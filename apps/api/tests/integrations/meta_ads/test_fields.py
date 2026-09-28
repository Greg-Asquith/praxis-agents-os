"""Checks stable Insights field categories before and after provider reads."""

import importlib
from datetime import date
from unittest.mock import AsyncMock

import pytest
from pydantic_ai import ModelRetry

from core.exceptions.integration import IntegrationValidationError
from integrations.meta_ads.client import MetaAdsClient
from integrations.meta_ads.operations.run_insights import run_insights
from integrations.meta_ads.tools.utils.validation import validated_insights_request


def query(fields, **changes):
    return validated_insights_request(
        max_rows=100,
        today=date(2026, 9, 24),
        fields=fields,
        since="2026-09-01",
        until="2026-09-10",
        **changes,
    )


async def report(fields, rows, **changes):
    provider = AsyncMock(spec=MetaAdsClient)
    provider.graph_get.return_value = {
        "data": [{"date_start": "2026-09-01", "date_stop": "2026-09-10", **row} for row in rows]
    }
    result = await run_insights(
        provider, account_id="1", request=query(fields, **changes), max_rows=100, poll_seconds=10
    )
    return result, provider.graph_get.call_args.kwargs["params"]


async def test_structured_field_validation_precedes_context_and_credentials(monkeypatch):
    tool = importlib.import_module("integrations.meta_ads.tools.run_insights")
    resolve_context = AsyncMock()
    resolve_client = AsyncMock()
    monkeypatch.setattr(tool, "run_context_fan_out", resolve_context)
    monkeypatch.setattr(tool, "meta_ads_client", resolve_client)
    with pytest.raises(ModelRetry, match="structured fields"):
        await tool.meta_ads_run_insights(
            object(), fields=["results"], since="2026-09-01", until="2026-09-10"
        )
    resolve_context.assert_not_awaited()
    resolve_client.assert_not_awaited()


async def test_unknown_field_names_still_reach_the_provider():
    result, params = await report(["future_metric"], [{"future_metric": "2"}, {}])
    assert "future_metric" in params["fields"].split(",")
    assert result.rows[0].metrics == {"future_metric": 2.0}
    assert result.rows[1].metrics == {"future_metric": None}


@pytest.mark.parametrize(
    "value",
    [
        "OUTCOME_SALES",
        "NaN",
    ],
)
async def test_known_metrics_cannot_be_reclassified_as_text_or_actions(value):
    with pytest.raises(IntegrationValidationError, match="metric"):
        await report(["spend"], [{"spend": value}])
