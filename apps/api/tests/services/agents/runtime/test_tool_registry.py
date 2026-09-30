# apps/api/tests/services/agents/runtime/test_tool_registry.py

"""Unit tests for the runtime tool registry contract."""

from dataclasses import replace
from uuid import uuid4

import pytest
from pydantic import BaseModel

from core.exceptions.general import AppValidationError
from integrations.airtable.tools import TOOL_DEFINITIONS as AIRTABLE_TOOL_DEFINITIONS
from integrations.bigquery.tools import TOOL_DEFINITIONS as BIGQUERY_TOOL_DEFINITIONS
from integrations.gmail.tools import TOOL_DEFINITIONS as GMAIL_TOOL_DEFINITIONS
from integrations.google_ads import PROVIDER as GOOGLE_ADS_PROVIDER
from integrations.google_ads.tools import TOOL_DEFINITIONS as GOOGLE_ADS_TOOL_DEFINITIONS
from integrations.google_ads.tools.utils import GOOGLE_ADS_BINDING
from integrations.google_analytics.tools import (
    TOOL_DEFINITIONS as GOOGLE_ANALYTICS_TOOL_DEFINITIONS,
)
from models.agent import Agent
from services.agents.runtime.delegation.build_delegation_tools import (
    DELEGATION_TOOL_DEFINITIONS,
)
from services.agents.runtime.delegation.summary import summarize_delegate_agent
from services.agents.runtime.delegation.tool_names import DELEGATE_TO_AGENT_TOOL_NAME
from services.agents.runtime.tools import permissions
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_EXTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_EXTERNAL_WRITE,
    TOOL_POLICY_APPROVAL,
    TOOL_POLICY_AUTO,
    IntegrationToolBinding,
    RuntimeToolDefinition,
    ToolEffectScope,
    validate_definition,
)
from services.agents.runtime.tools.registry import (
    RUNTIME_TOOL_CATALOG,
    build_runtime_tools,
    get_runtime_tool_definition,
    list_allowed_tool_definitions,
    list_selected_provider_keys,
    runtime_tool,
)
from services.agents.utils import validate_tool_configuration
from services.integrations.manifest import PROVIDER_MANIFESTS
from tests.factories import build_workspace


@pytest.fixture
def cleanup_test_tools():
    before = set(RUNTIME_TOOL_CATALOG)
    yield
    for name in set(RUNTIME_TOOL_CATALOG) - before:
        RUNTIME_TOOL_CATALOG.pop(name, None)


@pytest.fixture
def google_ads_manifest(monkeypatch):
    monkeypatch.setitem(
        PROVIDER_MANIFESTS,
        GOOGLE_ADS_PROVIDER.manifest.provider_key,
        GOOGLE_ADS_PROVIDER.manifest,
    )


def _noop() -> str:
    return "ok"


def _external_scope(_args: dict[str, object]) -> ToolEffectScope:
    return TOOL_EFFECT_SCOPE_EXTERNAL


def _bare_customer(customer_id: str) -> str:
    return customer_id


class _CodeReadOutput(BaseModel):
    customer_id: str


class _UnsafeNestedScope(BaseModel):
    customer_id: str


class _UnsafeScopeWrapper(BaseModel):
    target: _UnsafeNestedScope


def _unsafe_nested_scope(target: _UnsafeNestedScope) -> str:
    return target.customer_id


def _unsafe_wrapped_scope(payload: _UnsafeScopeWrapper) -> str:
    return payload.target.customer_id


def _agent(
    *,
    tool_names: list[str] | None = None,
    tool_policies: dict[str, str] | None = None,
    all_tools: bool = False,
    excluded_tool_names: list[str] | None = None,
) -> Agent:
    return Agent(
        name="Tool Test Agent",
        slug=f"tool-test-agent-{uuid4().hex[:8]}",
        instructions="Use configured tools.",
        workspace_id=uuid4(),
        created_by=uuid4(),
        tool_names=tool_names or [],
        tool_policies=tool_policies,
        all_tools=all_tools,
        excluded_tool_names=excluded_tool_names or [],
        model_provider="openai",
        model="gpt-6-luna",
    )


def test_runtime_owned_delegation_tool_resolves_as_a_write() -> None:
    definition = get_runtime_tool_definition(DELEGATE_TO_AGENT_TOOL_NAME)

    assert definition is not None
    assert definition.effect == TOOL_EFFECT_WRITE


def test_runtime_tool_decorator_rejects_duplicate_names(cleanup_test_tools) -> None:
    @runtime_tool(name="test_duplicate_tool", description="First registration.")
    def first_tool() -> str:
        return "first"

    with pytest.raises(RuntimeError, match="Duplicate runtime tool name"):

        @runtime_tool(name="test_duplicate_tool", description="Second registration.")
        def second_tool() -> str:
            return "second"

    assert RUNTIME_TOOL_CATALOG["test_duplicate_tool"].function is first_tool


@pytest.mark.parametrize(
    "definition",
    [
        RuntimeToolDefinition(name="BadName", function=_noop, description="Bad name."),
        RuntimeToolDefinition(name="bad_name", function=_noop, description="   "),
        RuntimeToolDefinition(
            name="bad_write",
            function=_noop,
            description="Write without approval.",
            effect="write",
            supports_approval=False,
        ),
        RuntimeToolDefinition(
            name="bad_read_scope",
            function=_noop,
            description="Read cannot be external.",
            effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
        ),
        RuntimeToolDefinition(
            name="bad_result_bound",
            function=_noop,
            description="Result bound must be positive.",
            max_result_chars=0,
        ),
        RuntimeToolDefinition(
            name="bad_public_result_bound",
            function=_noop,
            description="Public result bound must be positive.",
            max_public_result_chars=0,
        ),
        RuntimeToolDefinition(
            name="bad_version",
            function=_noop,
            description="Version must be positive.",
            version=0,
        ),
        RuntimeToolDefinition(
            name="bad_egress",
            function=_noop,
            description="Unknown egress.",
            egress="unknown",  # type: ignore[arg-type]
        ),
        RuntimeToolDefinition(
            name="bad_external_write_egress",
            function=_noop,
            description="External write without matching egress.",
            effect=TOOL_EFFECT_WRITE,
            effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
        ),
        RuntimeToolDefinition(
            name="bad_resolved_write_egress",
            function=_noop,
            description="Resolvable external write without matching egress.",
            effect=TOOL_EFFECT_WRITE,
            effect_scope_resolver=_external_scope,
        ),
        RuntimeToolDefinition(
            name="bad_read_external_write_egress",
            function=_noop,
            description="Read with write egress.",
            egress=TOOL_EGRESS_EXTERNAL_WRITE,
        ),
        RuntimeToolDefinition(
            name="bad_internal_write_egress",
            function=_noop,
            description="Internal write with outbound egress.",
            effect=TOOL_EFFECT_WRITE,
            egress="provider_query",
        ),
        RuntimeToolDefinition(
            name="bad_internal_write_binding",
            function=_noop,
            description="Internal write cannot use a writable integration query.",
            effect=TOOL_EFFECT_WRITE,
            egress="provider_query",
            integration_binding=replace(GOOGLE_ADS_BINDING, requires_write=True),
        ),
        RuntimeToolDefinition(
            name="bad_internal_write_url",
            function=_noop,
            description="Internal write cannot send arbitrary URLs.",
            effect=TOOL_EFFECT_WRITE,
            egress="arbitrary_url",
            integration_binding=GOOGLE_ADS_BINDING,
        ),
        RuntimeToolDefinition(
            name="run_script",
            function=_noop,
            description="Machinery cannot be wrapped.",
            code_eligible=True,
        ),
        RuntimeToolDefinition(
            name="bad_code_always_allowed",
            function=_noop,
            description="Always-allowed machinery cannot be wrapped.",
            code_eligible=True,
            configurable=False,
            always_allowed_when_mounted=True,
            supports_approval=False,
        ),
    ],
)
def test_validate_definition_rejects_invalid_invariants(
    definition: RuntimeToolDefinition,
) -> None:
    with pytest.raises(RuntimeError):
        validate_definition(definition)


def test_first_party_tool_egress_classifications_are_exhaustive() -> None:
    definitions = {
        definition.name: definition
        for definition in (
            *(
                definition
                for definition in RUNTIME_TOOL_CATALOG.values()
                if definition.integration_binding is None
                and not definition.name.startswith("test_")
            ),
            *AIRTABLE_TOOL_DEFINITIONS,
            *BIGQUERY_TOOL_DEFINITIONS,
            *GMAIL_TOOL_DEFINITIONS,
            *GOOGLE_ADS_TOOL_DEFINITIONS,
            *GOOGLE_ANALYTICS_TOOL_DEFINITIONS,
            *DELEGATION_TOOL_DEFINITIONS,
        )
    }
    expected = {
        "airtable_create_record": "external_write",
        "airtable_get_record": "provider_query",
        "airtable_list_records": "provider_query",
        "airtable_update_record": "external_write",
        "bigquery_get_table_schema": "none",
        "bigquery_list_tables": "none",
        "bigquery_run_query": "provider_query",
        "build_chart": "none",
        "classify": "provider_query",
        "create_artifact": "external_write",
        "create_skill": "none",
        "delegate_to_agent": "none",
        "edit_image": "none",
        "fetch_url": "arbitrary_url",
        "generate_image": "none",
        "generate_image_from_video": "none",
        "forget_memory": "none",
        "gmail_read_message": "provider_query",
        "gmail_search_messages": "provider_query",
        "gmail_send_message": "external_write",
        "google_ads_add_ad_group_negative_keywords": "external_write",
        "google_ads_add_campaign_negative_keywords": "external_write",
        "google_ads_add_negative_keywords": "external_write",
        "google_ads_create_keywords": "external_write",
        "google_ads_apply_recommendations": "external_write",
        "google_ads_assign_campaign_budgets": "external_write",
        "google_ads_create_campaign_budget": "external_write",
        "google_ads_dismiss_recommendations": "external_write",
        "google_ads_get_report_field": "provider_query",
        "google_ads_create_labels": "external_write",
        "google_ads_apply_labels": "external_write",
        "google_ads_remove_labels": "external_write",
        "google_ads_delete_labels": "external_write",
        "google_ads_create_negative_keyword_list": "external_write",
        "google_ads_link_negative_keyword_list": "external_write",
        "google_ads_remove_campaign_budgets": "external_write",
        "google_ads_list_report_fields": "provider_query",
        "google_ads_remove_negative_keywords": "external_write",
        "google_ads_remove_ad_group_negative_keywords": "external_write",
        "google_ads_remove_campaign_negative_keywords": "external_write",
        "google_ads_run_report": "provider_query",
        "google_ads_update_campaign_status": "external_write",
        "google_ads_update_campaign_budget_amounts": "external_write",
        "google_ads_update_device_bid_modifiers": "external_write",
        "google_ads_update_keywords": "external_write",
        "google_ads_remove_keywords": "external_write",
        "google_analytics_check_report_fields": "provider_query",
        "google_analytics_list_google_ads_links": "provider_query",
        "google_analytics_list_report_fields": "provider_query",
        "google_analytics_run_realtime_report": "provider_query",
        "google_analytics_run_report": "provider_query",
        "list_delegate_agents": "none",
        "list_artifacts": "none",
        "list_files": "none",
        "load_skill": "none",
        "read_artifact": "none",
        "read_document": "none",
        "read_file": "none",
        "read_skill_document": "none",
        "read_todos": "none",
        "report_completion": "none",
        "run_code": "none",
        "run_workflow": "none",
        "save_memory": "none",
        "search_knowledge": "none",
        "search_memory": "none",
        "search_skills": "none",
        "update_artifact": "external_write",
        "update_memory": "none",
        "update_skill": "none",
        "web_search": "provider_query",
        "write_file": "none",
        "write_todos": "none",
    }

    assert {name: definition.egress for name, definition in definitions.items()} == expected


def test_first_party_tool_code_eligibility_is_exhaustive() -> None:
    definitions = {
        definition.name: definition
        for definition in (
            *(
                definition
                for definition in RUNTIME_TOOL_CATALOG.values()
                if definition.integration_binding is None
                and not definition.name.startswith("test_")
            ),
            *AIRTABLE_TOOL_DEFINITIONS,
            *BIGQUERY_TOOL_DEFINITIONS,
            *GMAIL_TOOL_DEFINITIONS,
            *GOOGLE_ADS_TOOL_DEFINITIONS,
            *GOOGLE_ANALYTICS_TOOL_DEFINITIONS,
            *DELEGATION_TOOL_DEFINITIONS,
        )
    }
    expected_eligible = {
        "airtable_create_record",
        "airtable_get_record",
        "airtable_list_records",
        "airtable_update_record",
        "bigquery_get_table_schema",
        "bigquery_list_tables",
        "bigquery_run_query",
        "classify",
        "gmail_search_messages",
        "google_ads_add_ad_group_negative_keywords",
        "google_ads_add_campaign_negative_keywords",
        "google_ads_add_negative_keywords",
        "google_ads_create_keywords",
        "google_ads_apply_recommendations",
        "google_ads_assign_campaign_budgets",
        "google_ads_create_campaign_budget",
        "google_ads_dismiss_recommendations",
        "google_ads_get_report_field",
        "google_ads_create_labels",
        "google_ads_apply_labels",
        "google_ads_remove_labels",
        "google_ads_delete_labels",
        "google_ads_create_negative_keyword_list",
        "google_ads_link_negative_keyword_list",
        "google_ads_list_report_fields",
        "google_ads_remove_ad_group_negative_keywords",
        "google_ads_remove_campaign_budgets",
        "google_ads_remove_campaign_negative_keywords",
        "google_ads_remove_negative_keywords",
        "google_ads_run_report",
        "google_ads_update_campaign_status",
        "google_ads_update_campaign_budget_amounts",
        "google_ads_update_device_bid_modifiers",
        "google_ads_update_keywords",
        "google_ads_remove_keywords",
        "google_analytics_check_report_fields",
        "google_analytics_list_google_ads_links",
        "google_analytics_list_report_fields",
        "google_analytics_run_realtime_report",
        "google_analytics_run_report",
        "list_files",
        "read_file",
        "write_file",
    }

    assert {name for name, definition in definitions.items() if definition.code_eligible} == (
        expected_eligible
    )


@pytest.mark.parametrize(
    "function",
    [_bare_customer, _unsafe_nested_scope, _unsafe_wrapped_scope],
)
def test_integration_binding_rejects_untyped_scope_parameters(
    function,
    google_ads_manifest,
) -> None:
    definition = RuntimeToolDefinition(
        name="google_ads_unsafe_scope",
        function=function,
        description="Unsafe caller-owned scope.",
        provider="google_ads",
        integration_binding=GOOGLE_ADS_BINDING,
    )

    with pytest.raises(RuntimeError, match=r"scope|connection/account"):
        validate_definition(definition)


def test_validate_tool_configuration_rejects_unsupported_tool_policy(
    cleanup_test_tools,
) -> None:
    @runtime_tool(
        name="test_approval_only",
        description="Only runs with approval.",
        default_policy=TOOL_POLICY_APPROVAL,
        supports_auto=False,
    )
    def approval_only_tool() -> str:
        return "approved"

    with pytest.raises(AppValidationError) as exc_info:
        validate_tool_configuration(
            tool_names=["test_approval_only"],
            tool_policies={"test_approval_only": TOOL_POLICY_AUTO},
        )

    assert exc_info.value.field == "tool_policies"
    assert exc_info.value.details["unsupported_tool_policies"] == {
        "test_approval_only": {
            "tool_policy": TOOL_POLICY_AUTO,
            "allowed_tool_policies": [TOOL_POLICY_APPROVAL],
        }
    }


def test_tool_policy_prefers_agent_then_workspace_then_definition(
    cleanup_test_tools,
) -> None:
    @runtime_tool(
        name="test_approval_only",
        description="Only runs with approval.",
        default_policy=TOOL_POLICY_APPROVAL,
        supports_auto=False,
    )
    def approval_only_tool() -> str:
        return "approved"

    agent = _agent(
        tool_names=["test_runtime_context", "test_add_numbers", "test_approval_only"],
        # A stale auto override on an approval-only tool must not loosen it.
        tool_policies={"test_add_numbers": TOOL_POLICY_AUTO, "test_approval_only": "auto"},
    )
    tools = build_runtime_tools(
        agent,
        workspace_policies={
            "test_runtime_context": TOOL_POLICY_APPROVAL,
            "test_add_numbers": TOOL_POLICY_APPROVAL,
            "test_approval_only": TOOL_POLICY_AUTO,
        },
    )
    requires_approval = {tool.name: tool.requires_approval for tool in tools}

    assert requires_approval["test_runtime_context"] is True
    assert requires_approval["test_add_numbers"] is False
    assert requires_approval["test_approval_only"] is True


def test_build_runtime_tools_mounts_auto_tools_beside_the_selection() -> None:
    tools = build_runtime_tools(_agent(tool_names=["test_runtime_context", "test_add_numbers"]))

    names = [tool.name for tool in tools]
    auto_mounted = {
        name
        for name, definition in RUNTIME_TOOL_CATALOG.items()
        if definition.auto_mount and definition.integration_binding is None
    }
    assert auto_mounted <= set(names)
    assert names[-3:] == ["test_runtime_context", "test_add_numbers", "run_workflow"]
    # Mounted tools keep their definition's approval, timeout, and retry settings.
    for tool in tools:
        definition = RUNTIME_TOOL_CATALOG[tool.name]
        assert tool.requires_approval == (definition.default_policy == TOOL_POLICY_APPROVAL)
        assert (tool.timeout, tool.max_retries) == (definition.timeout, definition.max_retries)


@pytest.mark.deferred_tools
def test_code_eligible_tools_stay_direct_beside_run_workflow(
    cleanup_test_tools,
    google_ads_manifest,
) -> None:
    @runtime_tool(
        name="test_code_read",
        description="Read composable data.",
        code_eligible=True,
        output_model=_CodeReadOutput,
    )
    def code_read(query: str) -> dict[str, str]:
        return {"customer_id": query}

    @runtime_tool(
        name="test_context_code_read",
        description="Read scoped composable data.",
        code_eligible=True,
        integration_binding=GOOGLE_ADS_BINDING,
    )
    def context_code_read(query: str) -> str:
        return query

    @runtime_tool(name="test_direct_read", description="Read conversational data.")
    def direct_read(query: str) -> str:
        return query

    class _ActiveContext:
        def compatible_entries(self, _binding) -> list[object]:
            return []

    agent = _agent(
        tool_names=["test_code_read", "test_context_code_read", "test_direct_read"],
        tool_policies={"test_code_read": TOOL_POLICY_APPROVAL},
    )
    by_name = {
        tool.name: tool for tool in build_runtime_tools(agent, active_context=_ActiveContext())
    }

    assert by_name["test_code_read"].defer_loading is True
    assert by_name["test_code_read"].requires_approval is True
    assert by_name["test_code_read"].tool_def.return_schema["properties"] == {
        "customer_id": {"title": "Customer Id", "type": "string"}
    }
    assert "test_context_code_read" not in by_name
    assert by_name["run_workflow"].defer_loading is False
    assert "test_code_read" in by_name["run_workflow"].description
    assert "test_context_code_read" not in by_name["run_workflow"].description
    assert "test_direct_read" not in by_name["run_workflow"].description


def test_disallowed_tools_are_skipped_in_runtime_and_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def deny_test_add_numbers(definition: RuntimeToolDefinition, **_kwargs: object) -> bool:
        return definition.name != "test_add_numbers"

    monkeypatch.setattr(permissions, "is_tool_allowed", deny_test_add_numbers)

    tools = build_runtime_tools(_agent(tool_names=["test_runtime_context", "test_add_numbers"]))
    catalog = list_allowed_tool_definitions(workspace=object())

    assert [tool.name for tool in tools] == [
        "build_chart",
        "create_artifact",
        "create_skill",
        "forget_memory",
        "list_artifacts",
        "list_files",
        "load_skill",
        "read_artifact",
        "read_document",
        "read_file",
        "read_skill_document",
        "read_todos",
        "save_memory",
        "search_knowledge",
        "search_memory",
        "search_skills",
        "update_artifact",
        "update_memory",
        "update_skill",
        "write_file",
        "write_todos",
        "test_runtime_context",
        "run_workflow",
    ]
    assert "test_add_numbers" not in {definition.name for definition in catalog}


def test_workspace_disabled_tools_are_skipped_in_runtime_and_catalog() -> None:
    disabled = frozenset({"test_add_numbers"})
    agent = _agent(tool_names=["test_add_numbers"])
    workspace = object()

    tools = build_runtime_tools(
        agent,
        workspace=workspace,
        disabled_tool_names=disabled,
    )
    catalog = list_allowed_tool_definitions(
        workspace=workspace,
        disabled_tool_names=disabled,
    )

    assert "test_add_numbers" not in {tool.name for tool in tools}
    assert "test_add_numbers" not in {definition.name for definition in catalog}


def test_all_tools_agent_mounts_later_tools_minus_exclusions_and_filters(
    cleanup_test_tools,
    google_ads_manifest,
) -> None:
    agent = _agent(all_tools=True, excluded_tool_names=["test_all_excluded"])
    for name in ("test_all_added", "test_all_excluded", "test_all_disabled"):
        runtime_tool(name=name, description="Read data.")(_noop)
    runtime_tool(
        name="test_all_bound",
        description="Read scoped data.",
        integration_binding=GOOGLE_ADS_BINDING,
    )(_noop)

    mounted = {
        tool.name
        for tool in build_runtime_tools(
            agent,
            workspace=object(),
            disabled_tool_names=frozenset({"test_all_disabled"}),
        )
    }

    assert "test_all_added" in mounted
    assert {"test_all_excluded", "test_all_disabled", "test_all_bound"}.isdisjoint(mounted)


def test_selected_provider_keys_skip_unselected_and_disabled_tools() -> None:
    definitions = [
        RuntimeToolDefinition(
            name=f"bound_{provider_key}",
            function=_noop,
            description="Read.",
            integration_binding=IntegrationToolBinding(
                provider_keys=frozenset({provider_key}), resource_types=frozenset({"account"})
            ),
        )
        for provider_key in ("gmail", "notion", "airtable")
    ]

    provider_keys = list_selected_provider_keys(
        _agent(tool_names=["bound_gmail", "bound_notion"]),
        workspace=object(),
        disabled_tool_names=frozenset({"bound_notion"}),
        workspace_definitions=definitions,
    )

    assert provider_keys == frozenset({"gmail"})


def test_delegate_summary_counts_workspace_tools_for_all_tools_agents(
    cleanup_test_tools,
) -> None:
    runtime_tool(name="test_all_counted", description="Read data.")(_noop)
    workspace_definitions = [
        replace(RUNTIME_TOOL_CATALOG["test_all_counted"], name=name)
        for name in ("classifier_kept", "classifier_excluded")
    ]
    agent = _agent(all_tools=True, excluded_tool_names=["classifier_excluded"])
    agent.id = uuid4()

    summary = summarize_delegate_agent(
        agent,
        workspace=build_workspace(),
        workspace_definitions=workspace_definitions,
    )
    without_workspace_tools = summarize_delegate_agent(agent, workspace=build_workspace())

    assert summary.tool_count == without_workspace_tools.tool_count + 1
