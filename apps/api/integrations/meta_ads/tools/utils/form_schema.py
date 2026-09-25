# apps/api/integrations/meta_ads/tools/utils/form_schema.py

"""Builds Insights form metadata from the provider's request and field contracts."""

from typing import Any

from ...insights_fields import REPORT_FIELDS
from ...settings import meta_ads_settings
from ..schemas.insights import (
    ACTION_BREAKDOWNS,
    ATTRIBUTION_WINDOWS,
    BREAKDOWNS,
    FILTER_VALUE_KINDS,
    OBJECT_FILTERS,
    SORT_DIRECTIONS,
    MetaAdsInsightsInput,
)


def insights_form_schema() -> dict[str, Any]:
    """Returns the request schema with provider-owned choices for report controls."""
    schema = MetaAdsInsightsInput.model_json_schema()
    fields = schema["properties"]
    level = fields["level"]
    if "$ref" in level:
        fields["level"] = {**schema["$defs"][level["$ref"].rsplit("/", 1)[-1]], **level}
    fields["fields"]["items"]["examples"] = list(REPORT_FIELDS)
    fields["breakdowns"]["items"]["enum"] = sorted(BREAKDOWNS)
    fields["action_breakdowns"]["items"]["enum"] = sorted(ACTION_BREAKDOWNS)
    windows = next(
        item for item in fields["attribution_windows"]["anyOf"] if item["type"] == "array"
    )
    windows["items"]["enum"] = sorted(ATTRIBUTION_WINDOWS)
    fields["limit"]["maximum"] = meta_ads_settings.META_ADS_INSIGHTS_MAX_ROWS
    fields["sort"]["x-directions"] = list(SORT_DIRECTIONS)
    filters = schema["$defs"]["MetaAdsInsightsFilter"]["properties"]
    filters["field"]["examples"] = sorted(OBJECT_FILTERS)
    filters["operator"]["x-value-kinds"] = FILTER_VALUE_KINDS
    return schema


INSIGHTS_FORM_SCHEMA = insights_form_schema()
