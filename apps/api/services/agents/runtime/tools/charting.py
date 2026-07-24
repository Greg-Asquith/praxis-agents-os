# apps/api/services/agents/runtime/tools/charting.py

"""Runtime tool for presenting structured data as a chart."""

import math
import re
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from services.agents.runtime.tools.contract import ToolPresentation
from services.agents.runtime.tools.registry import runtime_tool

ChartType = Literal["line", "bar", "area", "scatter", "pie", "composed"]
ChartSeriesType = Literal["line", "bar", "area"]
ChartCurve = Literal["linear", "monotone", "step"]
ChartLineStyle = Literal["solid", "dashed", "dotted"]
ChartXAxisFormat = Literal["text", "number", "currency", "percent", "date", "datetime"]
ChartNumericFormat = Literal["number", "currency", "percent"]
ChartScalar = StrictStr | StrictInt | StrictFloat | StrictBool | None
HexColor = Annotated[StrictStr, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]

MAX_CHART_ROWS = 200
MAX_CHART_SERIES = 5
MAX_CHART_FIELDS = 20
MAX_CHART_TEXT_LENGTH = 500
_RESERVED_DATA_KEYS = frozenset({"__proto__", "constructor", "prototype"})
_INTEGER_PATTERN = re.compile(r"^[+-]?\d+$")
_NUMBER_PATTERN = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")


class ChartTheme(BaseModel):
    """Optional brand overrides; omitted colors follow the application theme."""

    model_config = ConfigDict(extra="forbid")

    background_color: HexColor | None = None
    text_color: HexColor | None = None
    grid_color: HexColor | None = None
    palette: list[HexColor] = Field(default_factory=list, max_length=12)


class ChartXAxis(BaseModel):
    """Category or scatter-X axis."""

    model_config = ConfigDict(extra="forbid")

    data_key: str = Field(
        min_length=1,
        max_length=100,
        description="Data-row field used for categories or scatter X values.",
    )
    label: str | None = Field(default=None, max_length=80)
    format: ChartXAxisFormat = "text"
    currency_code: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    tick_angle: int = Field(
        default=0,
        ge=-90,
        le=90,
        description="Rotate long category labels when needed.",
    )

    @field_validator("data_key")
    @classmethod
    def validate_data_key(cls, value: str) -> str:
        return _validate_data_key(value)


class ChartYAxis(BaseModel):
    """Numeric Y axis; add a second entry only for differently scaled series."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default="primary", min_length=1, max_length=40)
    label: str | None = Field(default=None, max_length=80)
    format: ChartNumericFormat = Field(
        default="number",
        description="Percent values are fractions of one (0.125 renders as 12.5%).",
    )
    currency_code: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    minimum: float | None = None
    maximum: float | None = None
    orientation: Literal["left", "right"] = "left"
    scale: Literal["auto", "linear", "log"] = "auto"

    @model_validator(mode="after")
    def validate_domain(self) -> Self:
        if self.minimum is not None and self.maximum is not None and self.minimum >= self.maximum:
            raise ValueError("y_axis.minimum must be less than y_axis.maximum")
        if self.scale == "log" and self.minimum is not None and self.minimum <= 0:
            raise ValueError("logarithmic y-axis minimum must be greater than zero")
        return self


class ChartSeries(BaseModel):
    """One numeric field plotted from each data row."""

    model_config = ConfigDict(extra="forbid")

    data_key: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=80)
    kind: ChartSeriesType | None = Field(
        default=None,
        description="Line, bar, or area when chart_type is composed.",
    )
    format: ChartNumericFormat = Field(
        default="number",
        description="Percent values are fractions of one (0.125 renders as 12.5%).",
    )
    currency_code: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    y_axis_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=40,
        description="Only needed when using more than one Y axis.",
    )
    color: HexColor | None = Field(
        default=None,
        description="Optional six-digit brand hex; omit to use the application palette.",
    )
    stack_id: str | None = Field(default=None, min_length=1, max_length=40)
    curve: ChartCurve = Field(
        default="monotone",
        description="Line shape for line and area series; use step for discrete changes.",
    )
    connect_nulls: bool = Field(
        default=False,
        description="Connect across missing values only when the gap is intentionally continuous.",
    )
    show_points: bool = Field(
        default=False,
        description="Show individual observations on line and area series.",
    )
    line_style: ChartLineStyle = Field(
        default="solid",
        description="Use dashed or dotted lines to distinguish forecasts, targets, or comparisons.",
    )

    @field_validator("data_key")
    @classmethod
    def validate_data_key(cls, value: str) -> str:
        return _validate_data_key(value)


class ChartOptions(BaseModel):
    """Small set of display choices that materially change a chart."""

    model_config = ConfigDict(extra="forbid")

    height: int = Field(default=320, ge=240, le=640)
    show_grid: bool = True
    show_legend: bool = True
    show_tooltip: bool = True
    horizontal: bool = Field(default=False, description="Render bar charts horizontally.")
    donut: bool = Field(default=False, description="Render pie charts with a hollow center.")
    pie_labels: bool = False
    theme: ChartTheme = Field(default_factory=ChartTheme)


class ChartSpec(BaseModel):
    """Compact, renderer-neutral chart specification designed for reliable tool calls."""

    model_config = ConfigDict(extra="forbid")

    chart_type: ChartType = Field(description="The simplest chart form suited to the data.")
    title: str = Field(min_length=1, max_length=120)
    subtitle: str | None = Field(default=None, max_length=240)
    caption: str | None = Field(default=None, max_length=500)
    x_axis: ChartXAxis
    y_axes: list[ChartYAxis] = Field(
        default_factory=lambda: [ChartYAxis()],
        min_length=1,
        max_length=4,
        description="Omit for a standard single Y axis.",
    )
    series: list[ChartSeries] = Field(min_length=1, max_length=MAX_CHART_SERIES)
    data: list[dict[str, ChartScalar]] = Field(min_length=1, max_length=MAX_CHART_ROWS)
    options: ChartOptions = Field(default_factory=ChartOptions)

    @model_validator(mode="after")
    def normalize_and_validate_chart(self) -> Self:
        series_keys = [series.data_key for series in self.series]
        if len(series_keys) != len(set(series_keys)):
            raise ValueError("chart series data_key values must be unique")
        if self.chart_type == "pie" and len(self.series) != 1:
            raise ValueError("pie charts require exactly one series")

        first_axis_id = self.y_axes[0].id
        for series in self.series:
            if series.y_axis_id is None:
                series.y_axis_id = first_axis_id
            if self.chart_type == "composed" and series.kind is None:
                series.kind = "line"
            elif self.chart_type != "composed":
                series.kind = None

        y_axis_ids = [axis.id for axis in self.y_axes]
        if len(y_axis_ids) != len(set(y_axis_ids)):
            raise ValueError("y_axes id values must be unique")
        unknown_y_axes = {
            series.y_axis_id for series in self.series if series.y_axis_id not in y_axis_ids
        }
        if unknown_y_axes:
            raise ValueError(
                "chart series reference unknown y_axis_id values: "
                f"{', '.join(sorted(str(value) for value in unknown_y_axes))}"
            )

        self.options.horizontal = self.options.horizontal and self.chart_type == "bar"
        self.options.donut = self.options.donut and self.chart_type == "pie"

        numeric_keys = set(series_keys)
        if self.chart_type == "scatter":
            numeric_keys.add(self.x_axis.data_key)
        populated_numeric_keys: set[str] = set()

        for index, row in enumerate(self.data):
            if len(row) > MAX_CHART_FIELDS:
                raise ValueError(
                    f"chart data row {index + 1} exceeds the {MAX_CHART_FIELDS}-field limit"
                )
            if self.x_axis.data_key not in row:
                raise ValueError(
                    f"chart data row {index + 1} is missing X-axis field {self.x_axis.data_key!r}"
                )
            for series_key in series_keys:
                row.setdefault(series_key, None)
            for key, value in row.items():
                _validate_data_key(key)
                if isinstance(value, str) and len(value) > MAX_CHART_TEXT_LENGTH:
                    raise ValueError(
                        f"chart data row {index + 1} field {key!r} exceeds "
                        f"{MAX_CHART_TEXT_LENGTH} characters"
                    )
                if key not in numeric_keys or value is None:
                    continue
                coerced = _coerce_number(value)
                if coerced is None:
                    raise ValueError(
                        f"chart data row {index + 1} field {key!r} must be numeric or null"
                    )
                row[key] = coerced
                populated_numeric_keys.add(key)

        missing_numeric_values = numeric_keys.difference(populated_numeric_keys)
        if missing_numeric_values:
            raise ValueError(
                "chart numeric fields must contain at least one value: "
                f"{', '.join(sorted(missing_numeric_values))}"
            )

        for axis in self.y_axes:
            if axis.scale != "log":
                continue
            axis_series_keys = {
                series.data_key for series in self.series if series.y_axis_id == axis.id
            }
            if any(
                row[key] is None or not isinstance(row[key], int | float) or row[key] <= 0
                for row in self.data
                for key in axis_series_keys
            ):
                raise ValueError(
                    f"logarithmic y-axis {axis.id!r} requires positive, non-null values"
                )
        return self


class ChartAck(BaseModel):
    """Compact model-visible confirmation; chart data remains in the tool arguments."""

    model_config = ConfigDict(extra="forbid")

    title: str
    points: int
    series: int


@runtime_tool(
    name="build_chart",
    provider="core",
    label="Build Chart",
    description=(
        "Present structured data as a chart. Supply chart type, title, X axis, series, and "
        "data. Omit Y axes, colors, and options unless the chart needs multiple scales, "
        "brand styling, or a non-default layout. Missing series values become null and "
        "numeric strings are accepted. Percent-formatted values are fractions of one "
        "(0.125 renders as 12.5%). Never invent source values."
    ),
    supports_approval=False,
    output_model=ChartAck,
    configurable=False,
    auto_mount=True,
    timeout=5,
    presentation=ToolPresentation(
        icon="chart",
        running_label="Building a Chart",
        completed_label="Built a Chart",
        failed_label="Couldn't Build the Chart",
    ),
)
def build_chart(spec: ChartSpec) -> ChartAck:
    """Acknowledge a validated chart without echoing its data into model history."""
    return ChartAck(title=spec.title, points=len(spec.data), series=len(spec.series))


def _coerce_number(value: ChartScalar) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return value if math.isfinite(value) else None
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not _NUMBER_PATTERN.fullmatch(normalized):
        return None
    number: int | float = (
        int(normalized) if _INTEGER_PATTERN.fullmatch(normalized) else float(normalized)
    )
    return number if math.isfinite(number) else None


def _validate_data_key(value: str) -> str:
    normalized = value.strip()
    if normalized != value or value in _RESERVED_DATA_KEYS or any(ord(char) < 32 for char in value):
        raise ValueError("chart data keys must be safe, trimmed field names")
    return value
