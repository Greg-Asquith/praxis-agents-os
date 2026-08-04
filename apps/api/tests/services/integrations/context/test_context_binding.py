# apps/api/tests/services/integrations/context/test_context_binding.py

"""Runtime integration-binding contract and filtering tests."""

from inspect import Parameter, Signature
from uuid import uuid4

import pytest

from models.agent import Agent
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_WRITE,
    IntegrationToolBinding,
    RuntimeToolDefinition,
    validate_definition,
)
from services.agents.runtime.tools.registry import (
    RUNTIME_TOOL_CATALOG,
    build_runtime_tools,
    register_tool_definition,
)
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry
from services.integrations.manifest import PROVIDER_MANIFESTS, IntegrationProviderManifest


@pytest.fixture
def integration_manifest():
    before = dict(PROVIDER_MANIFESTS)
    PROVIDER_MANIFESTS["test_provider"] = IntegrationProviderManifest(
        provider_key="test_provider",
        display_name="Test Provider",
        auth_modes=("api_key",),
        owner_scope="workspace",
        resource_types=("test_resource",),
        required_form_fields=("api_key",),
    )
    yield
    PROVIDER_MANIFESTS.clear()
    PROVIDER_MANIFESTS.update(before)


def _definition(function, **overrides) -> RuntimeToolDefinition:
    values = {
        "name": "bound_test_tool",
        "function": function,
        "description": "Operate on the active test resource.",
        "integration_binding": IntegrationToolBinding(
            provider_keys=frozenset({"test_provider"}),
            resource_types=frozenset({"test_resource"}),
        ),
    }
    values.update(overrides)
    return RuntimeToolDefinition(**values)


def test_binding_rejects_unknown_provider() -> None:
    with pytest.raises(RuntimeError, match="unknown provider"):
        validate_definition(_definition(lambda: None))


def test_write_binding_requires_write_tool(integration_manifest) -> None:
    with pytest.raises(RuntimeError, match="require a write tool"):
        validate_definition(
            _definition(
                lambda: None,
                integration_binding=IntegrationToolBinding(
                    provider_keys=frozenset({"test_provider"}),
                    resource_types=frozenset({"test_resource"}),
                    requires_write=True,
                ),
            )
        )

    validate_definition(
        _definition(
            lambda: None,
            effect=TOOL_EFFECT_WRITE,
            integration_binding=IntegrationToolBinding(
                provider_keys=frozenset({"test_provider"}),
                resource_types=frozenset({"test_resource"}),
                requires_write=True,
            ),
        )
    )


@pytest.mark.parametrize(
    "parameter_name",
    [
        "connection_id",
        "connection_label",
        "resource_id",
        "integration_resource_id",
        "account_id",
        "customer_id",
        "base_id",
        "mailbox",
        "principal",
    ],
)
def test_binding_rejects_model_selected_context_parameters(
    integration_manifest,
    parameter_name: str,
) -> None:
    def tool(**_kwargs: str) -> None:
        return None

    tool.__signature__ = Signature(  # type: ignore[attr-defined]
        [Parameter(parameter_name, Parameter.POSITIONAL_OR_KEYWORD, annotation=str)]
    )

    with pytest.raises(RuntimeError, match="context is server-resolved"):
        validate_definition(_definition(tool))


def test_build_runtime_tools_filters_only_bound_tools(integration_manifest) -> None:
    name = f"bound_test_{uuid4().hex}"

    def operation() -> str:
        return "ok"

    definition = _definition(operation, name=name)
    register_tool_definition(definition)
    try:
        agent = Agent(
            id=uuid4(),
            name="Bound tool agent",
            slug="bound-tool-agent",
            instructions="Use tools.",
            workspace_id=uuid4(),
            created_by=uuid4(),
            tool_names=[name, "test_add_numbers"],
        )
        compatible = ResolvedActiveContext(
            source="conversation",
            entries=(
                ResolvedContextEntry(
                    integration_resource_id=uuid4(),
                    provider_key="test_provider",
                    resource_type="test_resource",
                    external_id="one",
                    display_name="One",
                    connection_id=uuid4(),
                    connection_label="Primary",
                    connection_status="active",
                    write_allowed=True,
                ),
            ),
        )

        assert name not in {tool.name for tool in build_runtime_tools(agent)}
        mounted = {tool.name for tool in build_runtime_tools(agent, active_context=compatible)}
        assert name in mounted
        assert "test_add_numbers" in mounted
    finally:
        RUNTIME_TOOL_CATALOG.pop(name, None)
