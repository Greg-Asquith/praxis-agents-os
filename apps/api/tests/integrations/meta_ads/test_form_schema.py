"""Checks the server-owned contract consumed by the Insights approval form."""

import json
from pathlib import Path

from integrations.meta_ads.tools.run_insights import DEFINITION
from services.agents.runtime.tools.schemas import ToolPresentationEntry


def test_published_schema_matches_frontend_contract_fixture():
    fixture = (
        Path(__file__).parents[4] / "web/tests/integrations/meta-ads/insights-form-schema.json"
    )
    published = ToolPresentationEntry.from_definition(DEFINITION).model_dump(mode="json")
    assert published["ui"]["form_schema"] == json.loads(fixture.read_text())
