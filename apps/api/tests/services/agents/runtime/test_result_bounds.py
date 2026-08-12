# apps/api/tests/services/agents/runtime/test_result_bounds.py

"""Unit tests for dispatch-level tool-result bounds."""

from uuid import uuid4

import pytest
from pydantic import BaseModel
from pydantic_ai import ToolReturn

from services.agents.runtime.dispatch import (
    OutputContractError,
    prepare_public_result,
    truncate_result,
)
from services.agents.runtime.tools.contract import RuntimeToolDefinition
from utils.json_safe import REDACTED_VALUE


class StructuredOutput(BaseModel):
    content: str


class PublicOutput(BaseModel):
    rows: list[dict[str, str]]


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


def test_public_result_is_json_safe_redacted_validated_and_measured() -> None:
    result = ToolReturn(
        return_value={"rows": []},
        metadata={"public_result": {"rows": [{"id": uuid4(), "api_token": "must-not-persist"}]}},
    )

    chars = prepare_public_result(
        _definition(output_model=PublicOutput, max_public_result_chars=1_000),
        result,
    )

    row = result.metadata["public_result"]["rows"][0]
    assert isinstance(row["id"], str)
    assert row["api_token"] == REDACTED_VALUE
    assert chars is not None and chars > 0


@pytest.mark.parametrize(
    "metadata",
    [
        pytest.param({}, id="absent"),
        pytest.param({"public_result": None}, id="null"),
        pytest.param({"public_result": False}, id="false"),
        pytest.param({"public_result": 0}, id="zero"),
        pytest.param({"public_result": ""}, id="empty-string"),
        pytest.param({"public_result": {"rows": []}}, id="object"),
        pytest.param({"public_result": []}, id="list"),
    ],
)
def test_public_result_validation_honors_key_presence(metadata: dict[str, object]) -> None:
    result = ToolReturn(return_value={"model_only": "must-not-leak"}, metadata=metadata.copy())

    chars = prepare_public_result(
        _definition(max_public_result_chars=1_000),
        result,
    )

    if "public_result" not in metadata:
        assert chars is None
        assert "public_result" not in result.metadata
    else:
        assert chars is not None
        assert "public_result" in result.metadata
        assert result.metadata["public_result"] == metadata["public_result"]
        assert type(result.metadata["public_result"]) is type(metadata["public_result"])


@pytest.mark.parametrize("max_public_result_chars", [None, 10])
def test_public_result_requires_an_explicit_sufficient_bound(
    max_public_result_chars: int | None,
) -> None:
    result = ToolReturn(
        return_value={"rows": []},
        metadata={"public_result": {"rows": [{"content": "x" * 100}]}},
    )

    with pytest.raises(OutputContractError):
        prepare_public_result(
            _definition(max_public_result_chars=max_public_result_chars),
            result,
        )
