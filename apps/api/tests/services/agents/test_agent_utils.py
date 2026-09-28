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
