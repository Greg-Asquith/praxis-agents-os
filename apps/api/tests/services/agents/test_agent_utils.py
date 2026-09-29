# apps/api/tests/services/agents/test_agent_utils.py

"""Unit tests for agent service helpers."""

from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from core.exceptions.general import AppValidationError
from models.workspace import Workspace
from services.agents import utils as agent_utils
from services.agents.models.domain import PROVIDER_META, ModelInfo
from services.agents.models.resolution import resolve_agent_model
from services.agents.utils import (
    AGENT_SLUG_UNIQUE_INDEX,
    is_agent_slug_integrity_error,
    normalize_tool_selection,
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
            workspace=Workspace(),
            model_provider=PROVIDER_META,
            model="llama-probe",
            azure_deployment="partner-deployment",
        )


def test_agent_slug_integrity_error_matches_slug_unique_index() -> None:
    assert is_agent_slug_integrity_error(_integrity_error(AGENT_SLUG_UNIQUE_INDEX))


def test_validate_model_configuration_fills_missing_fields_from_workspace_default() -> None:
    workspace = Workspace(default_model_provider="anthropic", default_model="claude-sonnet-5")

    # Runtime would pair openai with the workspace's anthropic model and fail.
    with pytest.raises(AppValidationError, match="Unknown model"):
        validate_model_configuration(
            workspace=workspace, model_provider="openai", model=None, azure_deployment=None
        )

    validate_model_configuration(
        workspace=workspace, model_provider=None, model="claude-opus-5-5", azure_deployment=None
    )
    agent = SimpleNamespace(
        model_provider=None, model="claude-opus-5-5", model_settings=None, max_steps=None
    )
    resolved = resolve_agent_model(agent, workspace=workspace)
    assert (resolved.provider, resolved.model) == ("anthropic", "claude-opus-5-5")


def test_tool_selection_rejects_explicit_tools_while_all_tools_is_on() -> None:
    with pytest.raises(AppValidationError) as exc_info:
        normalize_tool_selection(
            all_tools=True,
            tool_names=["web_search"],
            excluded_tool_names=[],
            tool_policies=None,
        )

    assert exc_info.value.field == "tool_names"


def test_all_tools_selection_rejects_a_policy_on_an_excluded_tool() -> None:
    with pytest.raises(AppValidationError, match="must reference enabled tools"):
        normalize_tool_selection(
            all_tools=True,
            tool_names=[],
            excluded_tool_names=["web_search"],
            tool_policies={"web_search": "approval"},
        )
