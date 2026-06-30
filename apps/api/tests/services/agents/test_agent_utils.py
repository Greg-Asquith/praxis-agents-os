# apps/api/tests/services/agents/test_agent_utils.py

"""Unit tests for agent service helpers."""

from sqlalchemy.exc import IntegrityError

from services.agents.utils import (
    AGENT_SLUG_UNIQUE_INDEX,
    is_agent_slug_integrity_error,
    normalize_model_provider,
    validate_model_configuration,
)


class _Diag:
    def __init__(self, constraint_name: str) -> None:
        self.constraint_name = constraint_name


class _Orig:
    def __init__(self, constraint_name: str) -> None:
        self.diag = _Diag(constraint_name)


def _integrity_error(constraint_name: str) -> IntegrityError:
    return IntegrityError("insert", {}, _Orig(constraint_name))


def test_validate_model_configuration_returns_normalized_provider() -> None:
    normalized = validate_model_configuration(
        model_provider=" OPENAI ",
        model="gpt-5.4-mini",
        azure_deployment=None,
    )

    assert normalized == "openai"


def test_normalize_model_provider_collapses_blank_values() -> None:
    assert normalize_model_provider(None) is None
    assert normalize_model_provider("   ") is None
    assert normalize_model_provider(" Azure ") == "azure"


def test_agent_slug_integrity_error_matches_slug_unique_index() -> None:
    assert is_agent_slug_integrity_error(_integrity_error(AGENT_SLUG_UNIQUE_INDEX))


def test_agent_slug_integrity_error_ignores_other_constraints() -> None:
    assert not is_agent_slug_integrity_error(_integrity_error("future_agents_constraint"))
