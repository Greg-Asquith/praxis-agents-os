# apps/api/tests/services/agents/runtime/test_charting_tool.py

"""Tests for the compact renderer-neutral chart tool contract."""

from uuid import uuid4

import pytest
from pydantic import ValidationError
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from models.agent import Agent as AgentModel
from services.agents.runtime.tools.charting import ChartAck, ChartSpec, build_chart
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG, build_runtime_tools


def _spec(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "chart_type": "line",
        "title": "Weekly revenue",
        "x_axis": {"data_key": "week", "format": "date"},
        "series": [{"data_key": "revenue", "label": "Revenue"}],
        "data": [
            {"week": "2026-07-06", "revenue": "1250.5"},
            {"week": "2026-07-13", "revenue": 1810},
            {"week": "2026-07-20"},
        ],
    }
    values.update(overrides)
    return values


def _agent() -> AgentModel:
    return AgentModel(
        name="Chart test agent",
        slug=f"chart-test-{uuid4().hex[:8]}",
        instructions="Present requested charts.",
        workspace_id=uuid4(),
        created_by=uuid4(),
        tool_names=[],
        tool_policies={},
        model_provider="openai",
        model="gpt-5.4-mini",
    )


def test_build_chart_is_an_auto_mounted_compact_core_tool() -> None:
    definition = RUNTIME_TOOL_CATALOG["build_chart"]

    assert definition.output_model is ChartAck
    assert definition.auto_mount is True
    assert definition.configurable is False
    assert definition.supports_approval is False
    assert definition.effect == "read"
    assert definition.presentation.icon == "chart"
    assert "build_chart" in {tool.name for tool in build_runtime_tools(_agent())}

    schema = definition.serialized_input_schema()
    assert schema is not None
    assert schema["properties"]["chart_type"]["enum"] == [
        "line",
        "bar",
        "area",
        "scatter",
        "pie",
        "composed",
    ]
    assert schema["properties"]["data"]["maxItems"] == 200
    assert "y_axes" not in schema["required"]
    assert "options" not in schema["required"]
    assert schema["additionalProperties"] is False
    series_schema = schema["$defs"]["ChartSeries"]
    assert series_schema["additionalProperties"] is False
    assert series_schema["properties"]["curve"]["enum"] == ["linear", "monotone", "step"]
    assert series_schema["properties"]["line_style"]["enum"] == ["solid", "dashed", "dotted"]


def test_chart_defaults_reduce_agent_wiring_and_normalize_common_values() -> None:
    spec = ChartSpec.model_validate(_spec())
    acknowledgement = build_chart(spec)

    assert acknowledgement == ChartAck(title="Weekly revenue", points=3, series=1)
    assert spec.y_axes[0].id == "primary"
    assert spec.series[0].y_axis_id == "primary"
    assert spec.series[0].color is None
    assert spec.series[0].curve == "monotone"
    assert spec.series[0].line_style == "solid"
    assert spec.data[0]["revenue"] == 1250.5
    assert spec.data[2]["revenue"] is None
    assert spec.options.show_legend is True


def test_chart_spec_supports_axes_brand_colors_and_semantic_line_styles() -> None:
    spec = ChartSpec.model_validate(
        _spec(
            chart_type="composed",
            y_axes=[
                {
                    "id": "money",
                    "label": "Revenue",
                    "format": "currency",
                    "currency_code": "GBP",
                },
                {
                    "id": "rate",
                    "label": "Conversion",
                    "format": "percent",
                    "orientation": "right",
                },
            ],
            series=[
                {
                    "data_key": "revenue",
                    "label": "Revenue",
                    "kind": "bar",
                    "y_axis_id": "money",
                    "color": "#123456",
                },
                {
                    "data_key": "conversion",
                    "label": "Conversion",
                    "kind": "line",
                    "format": "percent",
                    "y_axis_id": "rate",
                    "color": "#FEDCBA",
                    "curve": "step",
                    "connect_nulls": True,
                    "show_points": True,
                    "line_style": "dashed",
                },
            ],
            data=[
                {"week": "2026-07-06", "revenue": 1250.5, "conversion": 18.2},
                {"week": "2026-07-13", "revenue": 1810, "conversion": 21.4},
            ],
        )
    )

    assert [axis.id for axis in spec.y_axes] == ["money", "rate"]
    assert [series.y_axis_id for series in spec.series] == ["money", "rate"]
    assert [series.color for series in spec.series] == ["#123456", "#FEDCBA"]
    assert spec.series[1].curve == "step"
    assert spec.series[1].connect_nulls is True
    assert spec.series[1].show_points is True
    assert spec.series[1].line_style == "dashed"


async def test_pydantic_ai_receives_only_the_compact_chart_acknowledgement() -> None:
    def chart_then_done(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        if not any(
            isinstance(part, ToolReturnPart) for message in messages for part in message.parts
        ):
            return ModelResponse(parts=[ToolCallPart(tool_name="build_chart", args=_spec())])
        return ModelResponse(parts=[TextPart(content="Chart ready.")])

    definition = RUNTIME_TOOL_CATALOG["build_chart"]
    agent = PydanticAgent(
        FunctionModel(chart_then_done),
        name="chart_contract_test_agent",
        tools=[definition.to_pydantic_tool()],
    )

    result = await agent.run("Put the weekly revenue in a chart.")

    assert result.output == "Chart ready."
    tool_returns = [
        part
        for message in result.all_messages()
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    assert len(tool_returns) == 1
    assert tool_returns[0].content == ChartAck(
        title="Weekly revenue",
        points=3,
        series=1,
    )


def test_pie_uses_theme_defaults_without_requiring_agent_colors() -> None:
    spec = ChartSpec.model_validate(
        _spec(
            chart_type="pie",
            data=[
                {"week": "2026-07-06", "revenue": 10},
                {"week": "2026-07-13", "revenue": 20},
            ],
        )
    )

    assert spec.series[0].color is None
    assert spec.options.theme.palette == []


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"data": [{"week": "2026-07-06", "revenue": "not a number"}]},
            "must be numeric or null",
        ),
        (
            {
                "chart_type": "pie",
                "series": [
                    {"data_key": "revenue", "label": "Revenue"},
                    {"data_key": "profit", "label": "Profit"},
                ],
                "data": [{"week": "2026-07-06", "revenue": 10, "profit": 4}],
            },
            "pie charts require exactly one series",
        ),
        (
            {
                "x_axis": {"data_key": "__proto__"},
                "data": [{"__proto__": "unsafe", "revenue": 10}],
            },
            "safe, trimmed field names",
        ),
        (
            {"y_axes": [{"minimum": 10, "maximum": 5}]},
            "minimum must be less than",
        ),
        (
            {
                "series": [
                    {
                        "data_key": "revenue",
                        "label": "Revenue",
                        "y_axis_id": "missing",
                    }
                ]
            },
            "unknown y_axis_id",
        ),
        (
            {
                "series": [
                    {
                        "data_key": "revenue",
                        "label": "Revenue",
                        "color": "brand-blue",
                    }
                ]
            },
            "string_pattern_mismatch",
        ),
        (
            {
                "y_axes": [{"scale": "log"}],
                "data": [
                    {"week": "2026-07-06", "revenue": 10},
                    {"week": "2026-07-13", "revenue": None},
                ],
            },
            "requires positive, non-null values",
        ),
        (
            {"options": {"animation": True}},
            "extra_forbidden",
        ),
        (
            {
                "series": [
                    {
                        "data_key": "revenue",
                        "label": "Revenue",
                        "stroke_dasharray": "1 1",
                    }
                ]
            },
            "extra_forbidden",
        ),
    ],
)
def test_chart_spec_rejects_unsafe_or_ambiguous_configs(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        ChartSpec.model_validate(_spec(**overrides))
