"""Settings contracts for history compaction and runaway-run limits."""

import pytest
from pydantic import ValidationError

from core.settings import Settings


def test_compaction_defaults_are_bounded() -> None:
    resolved = Settings()

    assert Settings.model_fields["AGENT_RUN_TOTAL_TOKENS_LIMIT"].default == 1_000_000
    assert resolved.AGENT_RUN_TOTAL_TOKENS_LIMIT is not None
    assert resolved.AGENT_HISTORY_CONTEXT_FRACTION == 0.6
    assert resolved.AGENT_HISTORY_SUMMARY_MAX_CHARS == 2000
    assert resolved.AZURE_OPENAI_CONTEXT_WINDOW == 128_000
    assert resolved.AZURE_OPENAI_CHARS_PER_TOKEN == 4.0
    assert resolved.DEFAULT_MODEL == "gpt-5.6-luna"


@pytest.mark.parametrize("fraction", [0, -0.1, 1.1])
def test_context_fraction_rejects_out_of_range_values(fraction: float) -> None:
    with pytest.raises(ValidationError):
        Settings(AGENT_HISTORY_CONTEXT_FRACTION=fraction)


def test_summary_cap_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(AGENT_HISTORY_SUMMARY_MAX_CHARS=0)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("AZURE_OPENAI_CONTEXT_WINDOW", 0),
        ("AZURE_OPENAI_CHARS_PER_TOKEN", 0),
    ],
)
def test_azure_context_accounting_must_be_positive(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value})
