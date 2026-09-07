# apps/api/tests/services/agents/test_agent_utils.py

"""Unit tests for agent service helpers."""

import pytest
from sqlalchemy.exc import IntegrityError

from core.exceptions.general import AppValidationError
from services.agents import utils as agent_utils
from services.agents.models.domain import PROVIDER_META, ModelInfo
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


def test_validate_model_configuration_accepts_partner_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        agent_utils,
        "find_model",
        lambda provider, model: ModelInfo(
            provider=provider,
            model=model,
            display_name="Llama probe",
            context_window=128_000,
            model_type="standard",
            vertex_model="meta/llama-probe",
        ),
    )

    normalized = validate_model_configuration(
        model_provider=PROVIDER_META,
        model="llama-probe",
        azure_deployment=None,
    )

    assert normalized == PROVIDER_META


def test_validate_model_configuration_rejects_azure_deployment_for_partner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        agent_utils,
        "find_model",
        lambda provider, model: ModelInfo(
            provider=provider,
            model=model,
            display_name="Llama probe",
            context_window=128_000,
            model_type="standard",
            vertex_model="meta/llama-probe",
        ),
    )

    with pytest.raises(AppValidationError, match="azure_deployment can only be used"):
        validate_model_configuration(
            model_provider=PROVIDER_META,
            model="llama-probe",
            azure_deployment="partner-deployment",
        )


def test_agent_slug_integrity_error_matches_slug_unique_index() -> None:
    assert is_agent_slug_integrity_error(_integrity_error(AGENT_SLUG_UNIQUE_INDEX))


def test_agent_slug_integrity_error_ignores_other_constraints() -> None:
    assert not is_agent_slug_integrity_error(_integrity_error("future_agents_constraint"))
