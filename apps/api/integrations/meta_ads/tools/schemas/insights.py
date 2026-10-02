# apps/api/integrations/meta_ads/tools/schemas/insights.py

"""Bounded inputs and typed rows for Meta Ads Insights."""

from typing import Annotated, Literal

from pydantic import Field

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...models import MetaAdsId, MetaAdsStrictModel, MetaAdsText

type MetaAdsInsightsLevel = Literal["account", "campaign", "adset", "ad"]
type MetaAdsFilterOperator = Literal[
    "EQUAL", "NOT_EQUAL", "IN", "NOT_IN", "CONTAIN", "NOT_CONTAIN", "GREATER_THAN", "LESS_THAN"
]
type MetaAdsFilterScalar = Annotated[str, Field(max_length=512)] | int | float

ATTRIBUTION_WINDOWS = frozenset({"1d_click", "7d_click", "28d_click", "1d_view", "1d_ev"})
BREAKDOWNS = frozenset(
    {
        "age",
        "gender",
        "country",
        "region",
        "publisher_platform",
        "platform_position",
        "device_platform",
        "impression_device",
    }
)
ACTION_BREAKDOWNS = frozenset({"action_type", "action_device", "action_destination"})
OBJECT_FILTERS = frozenset(
    f"{level}.{field}"
    for level in ("campaign", "adset", "ad")
    for field in ("name", "id", "effective_status")
)
SORT_DIRECTIONS = ("ascending", "descending")
FILTER_VALUE_KINDS = {
    "EQUAL": "scalar",
    "NOT_EQUAL": "scalar",
    "IN": "list",
    "NOT_IN": "list",
    "CONTAIN": "text",
    "NOT_CONTAIN": "text",
    "GREATER_THAN": "number",
    "LESS_THAN": "number",
}


class MetaAdsInsightsFilter(MetaAdsStrictModel):
    field: str = Field(min_length=1, max_length=128)
    operator: MetaAdsFilterOperator
    value: (
        MetaAdsFilterScalar
        | Annotated[list[MetaAdsFilterScalar], Field(min_length=1, max_length=50)]
    )


class MetaAdsInsightsInput(MetaAdsStrictModel):
    fields: list[Annotated[str, Field(max_length=128)]] = Field(min_length=1, max_length=30)
    since: str
    until: str
    level: MetaAdsInsightsLevel = "campaign"
    breakdowns: list[str] = Field(default_factory=list, max_length=3)
    action_breakdowns: list[str] = Field(default_factory=list, max_length=3)
    attribution_windows: list[str] | None = Field(default=None, min_length=1, max_length=5)
    time_increment: (
        Literal["all_days", "monthly"] | Annotated[int, Field(strict=True, ge=1, le=90)]
    ) = "all_days"
    filters: list[MetaAdsInsightsFilter] | None = Field(default=None, max_length=10)
    sort: str | None = None
    limit: int = Field(default=100, ge=1, strict=True)


class MetaAdsInsightsAction(MetaAdsStrictModel):
    action_type: str = Field(max_length=256)
    custom_conversion_id: MetaAdsId | None = None
    custom_conversion_name: MetaAdsText | None = None
    custom_event_name: MetaAdsText | None = None
    value: float | None
    windows: dict[str, float | None]
    breakdowns: dict[str, Annotated[str, Field(max_length=512)] | None] = Field(
        default_factory=dict
    )


class MetaAdsInsightsRow(MetaAdsStrictModel):
    keys: dict[str, Annotated[str, Field(max_length=512)] | None]
    metrics: dict[str, int | float | None]
    actions: dict[str, list[MetaAdsInsightsAction]]
    date_start: str
    date_stop: str


class MetaAdsInsightsData(MetaAdsStrictModel):
    rows: list[MetaAdsInsightsRow]
    row_count: int = Field(ge=0)
    truncated: bool
    truncation_note: str | None
    mode: Literal["direct", "background"]
    notes: list[str]
    currency: str = ""
    money_fields: list[str]
    timezone_name: str = ""
    level: MetaAdsInsightsLevel
    since: str
    until: str


class MetaAdsInsightsEntry(IntegrationFanOutEntry):
    data: MetaAdsInsightsData | None = None


class MetaAdsInsightsOutput(IntegrationFanOutOutput):
    results: list[MetaAdsInsightsEntry]
