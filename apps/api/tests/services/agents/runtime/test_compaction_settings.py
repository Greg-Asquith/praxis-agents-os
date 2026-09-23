"""Settings contracts for history compaction and runaway-run limits."""

import pytest
from pydantic import ValidationError

from core.settings import Settings


def test_compaction_defaults_are_bounded() -> None:
    fields = Settings.model_fields

    assert fields["AGENT_RUN_TOTAL_TOKENS_LIMIT"].default is None
    assert fields["AGENT_RUN_TOTAL_TOKENS_WINDOW_MULTIPLIER"].default == 8
    assert fields["AGENT_RUN_CACHED_TOKEN_WEIGHT"].default == 0.1
    assert fields["AGENT_HISTORY_CONTEXT_FRACTION"].default == 0.6
    assert fields["AGENT_HISTORY_SUMMARY_MAX_CHARS"].default == 2000
    assert fields["AZURE_OPENAI_CONTEXT_WINDOW"].default == 128_000
    assert fields["AZURE_OPENAI_CHARS_PER_TOKEN"].default == 4.0


@pytest.mark.parametrize(
    ("provider", "model"),
    [("google", "gemini-3.8-flash"), ("openai", "gpt-5.6-luna")],
)
def test_default_model_uses_environment_configuration(
    monkeypatch: pytest.MonkeyPatch, provider: str, model: str
) -> None:
    monkeypatch.setenv("DEFAULT_MODEL_PROVIDER", provider)
    monkeypatch.setenv("DEFAULT_MODEL", model)

    resolved = Settings()

    assert provider == resolved.DEFAULT_MODEL_PROVIDER
    assert model == resolved.DEFAULT_MODEL


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
        ("AGENT_RUN_TOTAL_TOKENS_LIMIT", 0),
        ("AGENT_RUN_TOTAL_TOKENS_LIMIT", 2**53),
        ("AGENT_RUN_TOTAL_TOKENS_WINDOW_MULTIPLIER", 0),
        ("AGENT_RUN_TOTAL_TOKENS_WINDOW_MULTIPLIER", 1.5),
        ("AGENT_RUN_TOTAL_TOKENS_WINDOW_MULTIPLIER", 2**53),
        ("AGENT_RUN_CACHED_TOKEN_WEIGHT", -0.1),
        ("AGENT_RUN_CACHED_TOKEN_WEIGHT", 1.1),
        ("AGENT_RUN_CACHED_TOKEN_WEIGHT", float("nan")),
        ("AGENT_RUN_CACHED_TOKEN_WEIGHT", float("inf")),
    ],
)
def test_invalid_backstop_settings_are_rejected(field, value) -> None:
    with pytest.raises(ValidationError, match=field):
        Settings(**{field: value})


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
