# apps/api/tests/services/agents/runtime/test_tool_registry.py

"""Unit tests for the runtime tool registry contract."""

from dataclasses import replace
from uuid import uuid4

import pytest
from pydantic import BaseModel, SecretStr

from core.exceptions.general import AppValidationError
from core.settings import settings
from integrations.airtable.tools import TOOL_DEFINITIONS as AIRTABLE_TOOL_DEFINITIONS
from integrations.bigquery.tools import TOOL_DEFINITIONS as BIGQUERY_TOOL_DEFINITIONS
from integrations.gmail.tools import TOOL_DEFINITIONS as GMAIL_TOOL_DEFINITIONS
from integrations.google_ads import PROVIDER as GOOGLE_ADS_PROVIDER
from integrations.google_ads.settings import google_ads_settings
from integrations.google_ads.tools import TOOL_DEFINITIONS as GOOGLE_ADS_TOOL_DEFINITIONS
from integrations.google_ads.tools.utils import GOOGLE_ADS_BINDING
from integrations.google_analytics.tools import (
    TOOL_DEFINITIONS as GOOGLE_ANALYTICS_TOOL_DEFINITIONS,
)
from models.agent import Agent
from services.agents.runtime.delegation.build_delegation_tools import (
    DELEGATION_TOOL_DEFINITIONS,
)
from services.agents.runtime.delegation.tool_names import DELEGATE_TO_AGENT_TOOL_NAME
from services.agents.runtime.tools import permissions
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_EXTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_EXTERNAL_WRITE,
    TOOL_POLICY_APPROVAL,
    TOOL_POLICY_AUTO,
    RuntimeToolDefinition,
    ToolEffectScope,
    validate_definition,
)
from services.agents.runtime.tools.registry import (
    RUNTIME_TOOL_CATALOG,
    build_runtime_tools,
    get_runtime_tool_definition,
    list_allowed_tool_definitions,
    runtime_tool,
)
from services.agents.utils import validate_tool_configuration
from services.integrations.manifest import PROVIDER_MANIFESTS


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
    code_mode_enabled: bool = False,
) -> Agent:
    return Agent(
        name="Tool Test Agent",
        slug=f"tool-test-agent-{uuid4().hex[:8]}",
        instructions="Use configured tools.",
        workspace_id=uuid4(),
        created_by=uuid4(),
        tool_names=tool_names or [],
        tool_policies=tool_policies,
        code_mode_enabled=code_mode_enabled,
        model_provider="openai",
        model="gpt-5.4-mini",
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
        RuntimeToolDefinition(
            name="bad_code_deferred",
            function=_noop,
            description="Deferred tools cannot be wrapped in v1.",
            code_eligible=True,
            defer_loading=True,
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
        "list_skills": "none",
        "read_artifact": "none",
        "read_document": "none",
        "read_file": "none",
        "read_skill": "none",
        "read_todos": "none",
        "report_completion": "none",
        "run_code": "none",
        "run_workflow": "none",
        "save_memory": "none",
        "search_knowledge": "none",
        "search_memory": "none",
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


def test_build_runtime_tools_preserves_core_tool_behavior() -> None:
    default_tools = build_runtime_tools(
        _agent(tool_names=["test_runtime_context", "test_add_numbers"])
    )
    approved_tools = build_runtime_tools(
        _agent(
            tool_names=["test_runtime_context", "test_add_numbers"],
            tool_policies={
                "test_runtime_context": TOOL_POLICY_APPROVAL,
                "test_add_numbers": TOOL_POLICY_APPROVAL,
            },
        )
    )

    assert [tool.name for tool in default_tools] == [
        "build_chart",
        "create_artifact",
        "create_skill",
        "forget_memory",
        "list_artifacts",
        "list_files",
        "list_skills",
        "read_artifact",
        "read_document",
        "read_file",
        "read_skill",
        "read_todos",
        "save_memory",
        "search_knowledge",
        "search_memory",
        "update_artifact",
        "update_memory",
        "update_skill",
        "write_file",
        "write_todos",
        "test_runtime_context",
        "test_add_numbers",
    ]
    auto_mounted_approval = {"create_skill", "update_skill"}
    assert [tool.requires_approval for tool in default_tools] == [
        *(tool.name in auto_mounted_approval for tool in default_tools[:-2]),
        True,
        False,
    ]
    assert [tool.timeout for tool in default_tools] == [
        5,
        30,
        15,
        15,
        15,
        10.0,
        15,
        30,
        15,
        settings.CHAT_ATTACHMENT_CONVERSION_TIMEOUT_SECONDS + 5.0,
        15,
        5,
        15,
        30,
        15,
        30,
        15,
        15,
        30.0,
        5,
        5,
        5,
    ]
    assert [tool.max_retries for tool in default_tools] == [*([None] * 21), 1]
    assert [tool.requires_approval for tool in approved_tools] == [
        *(tool.name in auto_mounted_approval for tool in approved_tools[:-2]),
        True,
        True,
    ]


def test_code_mode_replaces_every_eligible_non_deferred_tool_with_workflow_stubs(
    cleanup_test_tools,
) -> None:
    @runtime_tool(
        name="test_code_read",
        description="Read composable data.",
        code_eligible=True,
    )
    def code_read(query: str) -> str:
        return query

    @runtime_tool(
        name="test_code_write",
        description="Write composable data.",
        code_eligible=True,
        effect=TOOL_EFFECT_WRITE,
    )
    def code_write(value: str) -> str:
        return value

    @runtime_tool(
        name="test_direct_read",
        description="Read conversational data.",
        code_eligible=False,
    )
    def direct_read(query: str) -> str:
        return query

    agent = _agent(
        tool_names=["test_code_read", "test_code_write", "test_direct_read"],
        code_mode_enabled=True,
    )

    tools = build_runtime_tools(agent)
    names = {tool.name for tool in tools}
    workflow = next(tool for tool in tools if tool.name == "run_workflow")

    assert "test_code_read" not in names
    assert {"test_direct_read", "run_workflow"}.issubset(names)
    assert "test_code_write" not in names
    assert "async def test_code_read(*, query: str)" in workflow.description
    assert "async def test_code_write" in workflow.description
    assert "async def test_direct_read" not in workflow.description
    assert workflow.requires_approval is False
    assert workflow.max_retries == 1


def test_code_mode_wraps_approval_policy_but_keeps_deferred_tools_direct(
    cleanup_test_tools,
) -> None:
    @runtime_tool(
        name="test_approval_read",
        description="Read only after approval.",
        code_eligible=True,
    )
    def approval_read(query: str) -> str:
        return query

    @runtime_tool(
        name="test_deferred_read",
        description="Read after capability loading.",
        code_eligible=False,
        defer_loading=True,
    )
    def deferred_read(query: str) -> str:
        return query

    tools = build_runtime_tools(
        _agent(
            tool_names=["test_approval_read", "test_deferred_read"],
            tool_policies={"test_approval_read": TOOL_POLICY_APPROVAL},
            code_mode_enabled=True,
        )
    )

    by_name = {tool.name: tool for tool in tools}
    assert "test_approval_read" not in by_name
    assert by_name["test_deferred_read"].defer_loading is True
    assert "async def test_approval_read" in by_name["run_workflow"].description
    assert "async def test_deferred_read" not in by_name["run_workflow"].description


def test_code_mode_applies_integration_context_filter_before_both_mount_paths(
    cleanup_test_tools,
    google_ads_manifest,
) -> None:
    @runtime_tool(
        name="test_context_code_read",
        description="Read scoped composable data.",
        code_eligible=True,
        integration_binding=GOOGLE_ADS_BINDING,
    )
    def context_code_read(query: str) -> str:
        return query

    @runtime_tool(
        name="test_context_direct_read",
        description="Read scoped conversational data.",
        code_eligible=False,
        integration_binding=GOOGLE_ADS_BINDING,
    )
    def context_direct_read(query: str) -> str:
        return query

    class _ActiveContext:
        def __init__(self, compatible: bool) -> None:
            self.compatible = compatible

        def compatible_entries(self, _binding) -> list[object]:
            return [object()] if self.compatible else []

    agent = _agent(
        tool_names=["test_context_code_read", "test_context_direct_read"],
        code_mode_enabled=True,
    )
    without_context = build_runtime_tools(agent, active_context=_ActiveContext(False))
    wrapped_tool_names: list[str] = []
    with_context = build_runtime_tools(
        agent,
        active_context=_ActiveContext(True),
        wrapped_tool_names=wrapped_tool_names,
    )

    absent_workflow = next(tool for tool in without_context if tool.name == "run_workflow")
    present_workflow = next(tool for tool in with_context if tool.name == "run_workflow")
    assert "test_context_code_read" not in absent_workflow.description
    assert "test_context_direct_read" not in {tool.name for tool in without_context}
    assert "test_context_code_read" in present_workflow.description
    assert "test_context_code_read" in wrapped_tool_names
    assert "test_context_direct_read" in {tool.name for tool in with_context}


def test_google_ads_field_tools_follow_code_mode_and_safety_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    field_tool_names = {
        "google_ads_get_report_field",
        "google_ads_list_report_fields",
    }

    class _ActiveContext:
        def compatible_entries(self, binding) -> list[object]:
            return [object()] if "google_ads" in binding.provider_keys else []

    context = _ActiveContext()
    monkeypatch.setattr(
        google_ads_settings,
        "GOOGLE_ADS_DEVELOPER_TOKEN",
        SecretStr("developer-token"),
    )
    wrapped_tool_names: list[str] = []
    tools = build_runtime_tools(
        _agent(tool_names=[], code_mode_enabled=True),
        active_context=context,
        wrapped_tool_names=wrapped_tool_names,
    )
    workflow = next(tool for tool in tools if tool.name == "run_workflow")

    assert field_tool_names.issubset(wrapped_tool_names)
    assert field_tool_names.isdisjoint(tool.name for tool in tools)
    assert all(tool_name in workflow.description for tool_name in field_tool_names)

    disabled = build_runtime_tools(
        _agent(tool_names=[]),
        active_context=context,
        workspace=object(),
        disabled_tool_names=frozenset(field_tool_names),
    )
    assert field_tool_names.isdisjoint(tool.name for tool in disabled)

    monkeypatch.setattr(google_ads_settings, "GOOGLE_ADS_DEVELOPER_TOKEN", None)
    unavailable = build_runtime_tools(
        _agent(tool_names=[]),
        active_context=context,
    )
    assert field_tool_names.isdisjoint(tool.name for tool in unavailable)


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
        "list_skills",
        "read_artifact",
        "read_document",
        "read_file",
        "read_skill",
        "read_todos",
        "save_memory",
        "search_knowledge",
        "search_memory",
        "update_artifact",
        "update_memory",
        "update_skill",
        "write_file",
        "write_todos",
        "test_runtime_context",
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
