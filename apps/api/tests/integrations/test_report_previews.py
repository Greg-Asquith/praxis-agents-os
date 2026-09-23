"""Provider report contracts preserve metadata and errors in bounded previews."""

from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from integrations.google_ads.tools.run_report import DEFINITION as ADS
from integrations.google_analytics.tools.list_report_fields import DEFINITION as FIELDS
from integrations.google_analytics.tools.run_realtime_report import DEFINITION as REALTIME
from integrations.google_analytics.tools.run_report import DEFINITION as ANALYTICS
from integrations.google_search_console.tools.query_search_analytics import DEFINITION as SEARCH
from services.agents.runtime.structured_results import preview_structured_result, result_json

ANALYTICS_METADATA = {
    "currency_code": "GBP",
    "time_zone": "Europe/London",
    "sampled": True,
    "sampling_notes": ["Sampled report."],
    "active_metric_restrictions": [],
    "data_loss_from_other_row": False,
    "thresholded": False,
    "empty_reason": None,
}
ANALYTICS_DATA = {
    "totals": [{"activeUsers": 2_000}],
    "minimums": [{"activeUsers": 1}],
    "maximums": [{"activeUsers": 200}],
    "metric_headers": [{"name": "activeUsers", "type": "TYPE_INTEGER"}],
    "dimension_headers": ["country"],
}


@pytest.mark.parametrize(
    "definition,row,metadata",
    [
        (ADS, {"metrics": {"clicks": "10"}}, {"currency_code": "GBP"}),
        (
            ANALYTICS,
            {"country": "GB", "activeUsers": 2},
            {**ANALYTICS_DATA, "metadata": ANALYTICS_METADATA},
        ),
        (
            REALTIME,
            {"country": "GB", "activeUsers": 2},
            {**ANALYTICS_DATA, "window": [{"start_minutes_ago": 29, "end_minutes_ago": 0}]},
        ),
        (
            SEARCH,
            {
                "keys": {"query": "example"},
                "clicks": 2,
                "impressions": 10,
                "ctr": 0.2,
                "position": 1,
            },
            {
                "response_aggregation_type": "byProperty",
                "start_date": "2026-09-01",
                "end_date": "2026-09-20",
                "search_type": "web",
            },
        ),
    ],
)
def test_report_preview_keeps_provider_metadata_and_failed_accounts(definition, row, metadata):
    data = {
        **metadata,
        "rows": [row] * 1_000,
        "row_count": 1_000,
        "truncated": True,
        "truncation_note": "Provider page limit reached.",
    }
    entry = {
        "provider_key": definition.provider,
        "external_id": "123",
        "display_name": "Example",
        "status": "success",
        "data": data,
    }
    failure = {
        **entry,
        "external_id": "456",
        "status": "error",
        "data": None,
        "error_code": "denied",
        "error_message": "Access denied.",
    }
    original = definition.output_model.model_validate({"results": [entry, failure]}).model_dump(
        mode="json"
    )
    before = deepcopy(original)
    preview = preview_structured_result(
        original,
        limit=12_000,
        preview_rows=50,
        list_path=definition.preview_list_path,
        file_id=uuid4(),
        file_name="report.json",
    )
    projected = definition.output_model.model_validate(preview["data"]).model_dump(mode="json")
    assert original == before
    assert preview["lists"] == {"results.0.data.rows": {"total": 1_000, "shown": 50}}
    assert len(result_json(preview)) <= 12_000
    assert projected["results"][1] == original["results"][1]
    assert projected["results"][0]["data"] == {
        **original["results"][0]["data"],
        "rows": original["results"][0]["data"]["rows"][:50],
    }
    with pytest.raises(ValidationError):
        definition.output_model.model_validate(preview)


def test_field_discovery_previews_both_lists_without_changing_counts():
    field = {
        "api_name": "country",
        "ui_name": "Country",
        "description": "Description " * 20,
        "category": "Location",
        "custom": False,
    }
    data = {
        "dimensions": [field] * 200,
        "metrics": [
            {
                **field,
                "api_name": "activeUsers",
                "type": "TYPE_INTEGER",
                "blocked_reasons": ["NO_REVENUE_METRICS"],
            }
        ]
        * 200,
        "dimension_count": 200,
        "metric_count": 200,
        "truncated": False,
    }
    original = FIELDS.output_model.model_validate(
        {
            "results": [
                {
                    "provider_key": FIELDS.provider,
                    "external_id": "123",
                    "display_name": "Example",
                    "status": "success",
                    "data": data,
                }
            ]
        }
    ).model_dump(mode="json")
    preview = preview_structured_result(
        original,
        limit=48_000,
        preview_rows=50,
        list_path=FIELDS.preview_list_path,
        file_id=uuid4(),
        file_name="fields.json",
    )
    assert len(result_json(original)) > 48_000
    assert len(result_json(preview)) <= 48_000
    assert preview["lists"] == {
        "results.0.data.dimensions": {"total": 200, "shown": 50},
        "results.0.data.metrics": {"total": 200, "shown": 50},
    }
    projected = FIELDS.output_model.model_validate(preview["data"]).results[0].data
    assert projected.dimension_count == projected.metric_count == 200
    assert not projected.truncated
    assert projected.metrics[0].blocked_reasons == ["NO_REVENUE_METRICS"]
    assert len(original["results"][0]["data"]["metrics"]) == 200
