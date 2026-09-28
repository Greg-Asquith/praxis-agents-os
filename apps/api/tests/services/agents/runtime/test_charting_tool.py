# apps/api/tests/services/agents/runtime/test_charting_tool.py

"""Tests for the compact renderer-neutral chart tool contract."""

import pytest
from pydantic import ValidationError
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from services.agents.runtime.tools.charting import ChartAck, ChartSpec
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG


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
