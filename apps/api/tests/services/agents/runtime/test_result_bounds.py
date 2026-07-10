# apps/api/tests/services/agents/runtime/test_result_bounds.py

"""Unit tests for dispatch-level tool-result bounds."""

from pydantic import BaseModel
from pydantic_ai import ToolReturn

from services.agents.runtime.dispatch import truncate_result
from services.agents.runtime.tools.contract import RuntimeToolDefinition


class StructuredOutput(BaseModel):
    content: str


def _definition(**overrides) -> RuntimeToolDefinition:
    values = {
        "name": "bounded_result",
        "function": lambda: None,
        "description": "Return content for result-bound tests.",
    }
    values.update(overrides)
    return RuntimeToolDefinition(**values)


def test_over_limit_string_keeps_head_tail_and_exact_marker() -> None:
    result = "a" * 80 + "b" * 20 + "c" * 20

    bounded, size = truncate_result(_definition(), result, default_limit=100)

    assert isinstance(bounded, str)
    assert bounded.startswith("a" * 80)
    assert bounded.endswith("c" * 20)
    assert "20 characters (~5 tokens) elided" in bounded
    assert "narrower arguments, pagination, or an offset" in bounded
    assert len(bounded) <= 100 + 200
    assert size.chars == len(bounded)
    assert size.truncated is True
    assert size.original_chars == 120
    assert size.oversized is True


def test_at_or_under_limit_returns_same_object() -> None:
    result = "within-bound"

    bounded, size = truncate_result(_definition(), result, default_limit=len(result))

    assert bounded is result
    assert size.chars == len(result)
    assert size.truncated is False
    assert size.oversized is False


def test_none_default_disables_truncation() -> None:
    result = "x" * 100

    bounded, size = truncate_result(_definition(), result, default_limit=None)

    assert bounded is result
    assert size.truncated is False


def test_per_tool_limit_overrides_default_in_both_directions() -> None:
    result = "x" * 50

    bounded, _size = truncate_result(
        _definition(max_result_chars=20),
        result,
        default_limit=100,
    )
    unbounded, _size = truncate_result(
        _definition(max_result_chars=100),
        result,
        default_limit=20,
    )

    assert bounded != result
    assert unbounded is result


def test_structured_and_declared_outputs_are_measured_but_never_cut() -> None:
    mapping = {"content": "x" * 100}
    rich = ToolReturn(return_value="x" * 100)
    declared_string = "x" * 100

    mapping_result, mapping_size = truncate_result(_definition(), mapping, default_limit=10)
    rich_result, rich_size = truncate_result(_definition(), rich, default_limit=10)
    declared_result, declared_size = truncate_result(
        _definition(output_model=StructuredOutput),
        declared_string,
        default_limit=10,
    )

    assert mapping_result is mapping
    assert mapping_size.oversized is True
    assert mapping_size.truncated is False
    assert rich_result is rich
    assert rich_size.oversized is True
    assert rich_size.truncated is False
    assert declared_result is declared_string
    assert declared_size.oversized is True
    assert declared_size.truncated is False


def test_truncation_is_deterministic() -> None:
    result = "prefix" * 1000 + "漢字" * 1000 + "suffix" * 1000

    first, first_size = truncate_result(_definition(), result, default_limit=100)
    second, second_size = truncate_result(_definition(), result, default_limit=100)

    assert first == second
    assert first_size == second_size
