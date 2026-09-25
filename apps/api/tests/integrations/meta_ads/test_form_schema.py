"""Checks the server-owned contract consumed by the Insights approval form."""

import json
from pathlib import Path

from integrations.meta_ads.insights_fields import REPORT_FIELDS, UNSUPPORTED_STRUCTURED_FIELDS
from integrations.meta_ads.settings import meta_ads_settings
from integrations.meta_ads.tools.run_insights import DEFINITION
from integrations.meta_ads.tools.schemas.insights import (
    BREAKDOWNS,
    FILTER_VALUE_KINDS,
    MetaAdsInsightsInput,
)
from integrations.meta_ads.tools.utils.form_schema import insights_form_schema
from services.agents.runtime.tools.schemas import ToolPresentationEntry


def test_published_schema_matches_frontend_contract_fixture():
    fixture = (
        Path(__file__).parents[4] / "web/tests/integrations/meta-ads/insights-form-schema.json"
    )
    published = ToolPresentationEntry.from_definition(DEFINITION).model_dump(mode="json")
    assert published["ui"]["form_schema"] == json.loads(fixture.read_text())


def test_form_choices_and_defaults_follow_request_contract(monkeypatch):
    monkeypatch.setattr(meta_ads_settings, "META_ADS_INSIGHTS_MAX_ROWS", 500)
    schema = insights_form_schema()
    fields = schema["properties"]
    request = MetaAdsInsightsInput(fields=["spend"], since="2026-09-01", until="2026-09-24")
    for name in ("level", "limit", "time_increment"):
        assert fields[name]["default"] == getattr(request, name)
    assert fields["limit"]["maximum"] == 500
    assert set(fields["breakdowns"]["items"]["enum"]) == BREAKDOWNS
    assert fields["fields"]["items"]["examples"] == list(REPORT_FIELDS)
    assert not UNSUPPORTED_STRUCTURED_FIELDS.intersection(REPORT_FIELDS)
    operators = schema["$defs"]["MetaAdsInsightsFilter"]["properties"]["operator"]
    assert operators["x-value-kinds"] == FILTER_VALUE_KINDS
    assert set(schema["$defs"]["MetaAdsFilterOperator"]["enum"]) == set(FILTER_VALUE_KINDS)
