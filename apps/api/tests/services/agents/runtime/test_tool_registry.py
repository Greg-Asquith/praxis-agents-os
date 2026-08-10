# apps/api/tests/services/agents/runtime/test_tool_registry.py

"""Unit tests for the runtime tool registry contract."""

from typing import get_args, get_type_hints
from uuid import uuid4

import pytest
from pydantic import BaseModel

from core.exceptions.general import AppValidationError
from integrations.airtable.tools import TOOL_DEFINITIONS as AIRTABLE_TOOL_DEFINITIONS
from integrations.airtable.tools.create_record import (
    DEFINITION as AIRTABLE_CREATE_RECORD_DEFINITION,
)
from integrations.airtable.tools.get_record import DEFINITION as AIRTABLE_GET_RECORD_DEFINITION
from integrations.airtable.tools.list_records import DEFINITION as AIRTABLE_LIST_RECORDS_DEFINITION
from integrations.airtable.tools.update_record import (
    DEFINITION as AIRTABLE_UPDATE_RECORD_DEFINITION,
)
from integrations.bigquery.tools import TOOL_DEFINITIONS as BIGQUERY_TOOL_DEFINITIONS
from integrations.bigquery.tools.run_query import DEFINITION as BIGQUERY_RUN_QUERY_DEFINITION
from integrations.gmail.tools import TOOL_DEFINITIONS as GMAIL_TOOL_DEFINITIONS
from integrations.gmail.tools.read_message import DEFINITION as GMAIL_READ_MESSAGE_DEFINITION
from integrations.gmail.tools.search_messages import (
    DEFINITION as GMAIL_SEARCH_MESSAGES_DEFINITION,
)
from integrations.gmail.tools.send_message import DEFINITION as GMAIL_SEND_MESSAGE_DEFINITION
from integrations.google_ads import PROVIDER as GOOGLE_ADS_PROVIDER
from integrations.google_ads.references import GoogleAdsCampaignReference
from integrations.google_ads.tools import TOOL_DEFINITIONS as GOOGLE_ADS_TOOL_DEFINITIONS
from integrations.google_ads.tools.add_negative_keywords import (
    DEFINITION as GOOGLE_ADS_ADD_NEGATIVE_KEYWORDS_DEFINITION,
)
from integrations.google_ads.tools.create_negative_keyword_list import (
    DEFINITION as GOOGLE_ADS_CREATE_NEGATIVE_KEYWORD_LIST_DEFINITION,
)
from integrations.google_ads.tools.remove_negative_keywords import (
    DEFINITION as GOOGLE_ADS_REMOVE_NEGATIVE_KEYWORDS_DEFINITION,
)
from integrations.google_ads.tools.run_report import (
    DEFINITION as GOOGLE_ADS_RUN_REPORT_DEFINITION,
)
from integrations.google_ads.tools.update_campaign_status import (
    DEFINITION as GOOGLE_ADS_UPDATE_CAMPAIGN_STATUS_DEFINITION,
    google_ads_update_campaign_status,
)
from integrations.google_ads.tools.utils import GOOGLE_ADS_BINDING
from models.agent import Agent
from services.agents.models.domain import ModelConfigurationError
from services.agents.runtime.delegation.build_delegation_tools import (
    DELEGATE_TO_AGENT_DEFINITION,
    DELEGATION_TOOL_DEFINITIONS,
)
from services.agents.runtime.delegation.tool_names import DELEGATE_TO_AGENT_TOOL_NAME
from services.agents.runtime.tools import permissions
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_EXTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_EXTERNAL_WRITE,
    TOOL_EGRESS_NONE,
    TOOL_POLICY_APPROVAL,
    TOOL_POLICY_AUTO,
    RuntimeToolDefinition,
    ToolEffectScope,
    ToolFieldColumn,
    ToolFieldPresentation,
    ToolPresentation,
    validate_definition,
)
from services.agents.runtime.tools.registry import (
    RUNTIME_TOOL_CATALOG,
    build_runtime_tools,
    get_runtime_tool_definition,
    list_allowed_tool_definitions,
    runtime_tool,
)
from services.agents.runtime.tools.schemas import ToolPresentationRead
from services.agents.utils import validate_tool_configuration
from services.completion_contract import REPORT_COMPLETION_TOOL_NAME
from services.integrations.manifest import PROVIDER_MANIFESTS
from services.memories.domain import MemoryKind, MemoryScope, MemoryType


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


@pytest.mark.parametrize(
    "tool_name",
    ["delegate_to_agent", "fetch_url", "web_search"],
)
def test_long_running_tools_have_no_outer_execution_deadline(tool_name: str) -> None:
    definition = get_runtime_tool_definition(tool_name)

    assert definition is not None
    assert definition.timeout is None


def _scoped_campaign(campaign: GoogleAdsCampaignReference) -> str:
    return campaign.external_id


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


def _entity_value(value: str, scope: str = "default") -> str:
    return f"{scope}:{value}"


def _agent(
    *,
    tool_names: list[str] | None = None,
    tool_policies: dict[str, str] | None = None,
) -> Agent:
    return Agent(
        name="Tool Test Agent",
        slug=f"tool-test-agent-{uuid4().hex[:8]}",
        instructions="Use configured tools.",
        workspace_id=uuid4(),
        created_by=uuid4(),
        tool_names=tool_names or [],
        tool_policies=tool_policies,
        model_provider="openai",
        model="gpt-5.4-mini",
    )


def test_runtime_tool_decorator_registers_definition_with_derived_label(
    cleanup_test_tools,
) -> None:
    @runtime_tool(name="test_echo_value", description="Echo a value.")
    def echo_value(value: str) -> str:
        return value

    definition = RUNTIME_TOOL_CATALOG["test_echo_value"]

    assert definition.function is echo_value
    assert definition.provider == "core"
    assert definition.label == "Test echo value"
    assert definition.effect == "read"
    assert definition.effect_scope == "internal"
    assert definition.egress == TOOL_EGRESS_NONE
    assert definition.allowed_policies() == frozenset({TOOL_POLICY_AUTO, TOOL_POLICY_APPROVAL})
    assert definition.version == 1
    assert definition.serialized_input_schema() == {
        "additionalProperties": False,
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
        "type": "object",
    }


def test_runtime_tool_decorator_accepts_explicit_version(cleanup_test_tools) -> None:
    @runtime_tool(name="test_versioned_tool", description="Versioned.", version=3)
    def versioned_tool(value: int) -> int:
        return value

    assert RUNTIME_TOOL_CATALOG["test_versioned_tool"].version == 3


def test_registered_function_schemas_are_cached() -> None:
    for definition in RUNTIME_TOOL_CATALOG.values():
        schema = definition.serialized_input_schema()
        assert schema is not None
        assert schema is definition.serialized_input_schema()
        assert schema["type"] == "object"


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
    ],
)
def test_validate_definition_rejects_invalid_invariants(
    definition: RuntimeToolDefinition,
) -> None:
    with pytest.raises(RuntimeError):
        validate_definition(definition)


@pytest.mark.parametrize(
    "definition",
    [
        RuntimeToolDefinition(name="valid_read", function=_noop, description="Read."),
        RuntimeToolDefinition(
            name="valid_internal_write",
            function=_noop,
            description="Internal write.",
            effect=TOOL_EFFECT_WRITE,
        ),
        RuntimeToolDefinition(
            name="valid_external_write",
            function=_noop,
            description="External write.",
            effect=TOOL_EFFECT_WRITE,
            effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
            egress=TOOL_EGRESS_EXTERNAL_WRITE,
        ),
        RuntimeToolDefinition(
            name="valid_resolved_write",
            function=_noop,
            description="Resolved write.",
            effect=TOOL_EFFECT_WRITE,
            effect_scope_resolver=_external_scope,
            egress=TOOL_EGRESS_EXTERNAL_WRITE,
        ),
    ],
)
def test_validate_definition_accepts_egress_invariants(
    definition: RuntimeToolDefinition,
) -> None:
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
        "create_artifact": "external_write",
        "delegate_to_agent": "none",
        "fetch_url": "arbitrary_url",
        "forget_memory": "none",
        "gmail_read_message": "provider_query",
        "gmail_search_messages": "provider_query",
        "gmail_send_message": "external_write",
        "google_ads_list_accounts": "provider_query",
        "google_ads_add_negative_keywords": "external_write",
        "google_ads_create_negative_keyword_list": "external_write",
        "google_ads_link_negative_keyword_list": "external_write",
        "google_ads_remove_negative_keywords": "external_write",
        "google_ads_run_report": "provider_query",
        "google_ads_update_campaign_status": "external_write",
        "list_delegate_agents": "none",
        "list_files": "none",
        "read_document": "none",
        "read_file": "none",
        "read_todos": "none",
        "report_completion": "none",
        "save_memory": "none",
        "search_knowledge": "none",
        "search_memory": "none",
        "update_artifact": "external_write",
        "update_memory": "none",
        "web_search": "provider_query",
        "write_file": "none",
        "write_todos": "none",
    }

    assert {name: definition.egress for name, definition in definitions.items()} == expected


def test_validate_definition_rejects_editable_result_fields() -> None:
    definition = RuntimeToolDefinition(
        name="bad_editable_result",
        function=_noop,
        description="Result fields are display-only.",
        presentation=ToolPresentation(
            result_fields=(ToolFieldPresentation(key="result", label="Result", editable=True),)
        ),
    )

    with pytest.raises(RuntimeError, match="result presentation fields cannot be editable"):
        validate_definition(definition)


def test_integration_binding_accepts_scope_only_in_typed_reference(google_ads_manifest) -> None:
    definition = RuntimeToolDefinition(
        name="google_ads_scoped_campaign",
        function=_scoped_campaign,
        description="Read one selected campaign.",
        provider="google_ads",
        integration_binding=GOOGLE_ADS_BINDING,
        presentation=ToolPresentation(
            arg_fields=(
                ToolFieldPresentation(
                    key="campaign",
                    label="Campaign",
                    format="entity",
                    entity_kind="google_ads_campaign",
                ),
            )
        ),
    )

    validate_definition(definition)


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


@pytest.mark.parametrize(
    ("field", "error"),
    [
        (
            ToolFieldPresentation(key="choice", label="Choice", options=("One", "Two")),
            "options and placeholders require editable fields",
        ),
        (
            ToolFieldPresentation(key="hint", label="Hint", placeholder="Enter a value"),
            "options and placeholders require editable fields",
        ),
        (
            ToolFieldPresentation(
                key="choice",
                label="Choice",
                editable=True,
                options=("One", "   "),
            ),
            "options must not be blank",
        ),
        (
            ToolFieldPresentation(
                key="choice",
                label="Choice",
                editable=True,
                options=("One", " One "),
            ),
            "options must be unique",
        ),
        (
            ToolFieldPresentation(key="enabled", label="Enabled", format="boolean", editable=True),
            "must use an editable format",
        ),
        (
            ToolFieldPresentation(
                key="count",
                label="Count",
                format="number",
                editable=True,
                options=("One", "Two"),
            ),
            "options require a string-shaped format",
        ),
    ],
)
def test_validate_definition_rejects_invalid_field_presentation(
    field: ToolFieldPresentation,
    error: str,
) -> None:
    definition = RuntimeToolDefinition(
        name="bad_field_presentation",
        function=_noop,
        description="Invalid field presentation.",
        presentation=ToolPresentation(arg_fields=(field,)),
    )

    with pytest.raises(RuntimeError, match=error):
        validate_definition(definition)


@pytest.mark.parametrize(
    ("field", "error"),
    [
        (
            ToolFieldPresentation(key="value", label="Value", format="entity"),
            "require an entity kind",
        ),
        (
            ToolFieldPresentation(key="value", label="Value", entity_kind="file"),
            "cannot set entity kind",
        ),
        (
            ToolFieldPresentation(
                key="value",
                label="Value",
                format="entity",
                entity_kind="file",
                depends_on=("missing",),
            ),
            "dependencies must name input arguments",
        ),
    ],
)
def test_validate_definition_rejects_invalid_entity_metadata(
    field: ToolFieldPresentation,
    error: str,
) -> None:
    definition = RuntimeToolDefinition(
        name="bad_entity_field",
        function=_entity_value,
        description="Invalid entity presentation.",
        presentation=ToolPresentation(arg_fields=(field,)),
    )

    with pytest.raises(RuntimeError, match=error):
        validate_definition(definition)


def test_validate_definition_rejects_secondary_result_fields() -> None:
    definition = RuntimeToolDefinition(
        name="bad_secondary_result",
        function=_noop,
        description="Result fields are never secondary.",
        presentation=ToolPresentation(
            result_fields=(ToolFieldPresentation(key="result", label="Result", secondary=True),)
        ),
    )

    with pytest.raises(RuntimeError, match="result presentation fields cannot be secondary"):
        validate_definition(definition)


def test_validate_definition_rejects_blank_approve_label() -> None:
    definition = RuntimeToolDefinition(
        name="bad_approve_label",
        function=_noop,
        description="Approval labels must carry an action.",
        presentation=ToolPresentation(approve_label="   "),
    )

    with pytest.raises(RuntimeError, match="approve label must not be blank"):
        validate_definition(definition)


def test_validate_definition_accepts_url_and_list_result_fields() -> None:
    definition = RuntimeToolDefinition(
        name="rich_results",
        function=_noop,
        description="Rich display-only results.",
        presentation=ToolPresentation(
            result_fields=(
                ToolFieldPresentation(key="link", label="Link", format="url"),
                ToolFieldPresentation(key="items", label="Items", format="list"),
            )
        ),
    )

    validate_definition(definition)


@pytest.mark.parametrize(
    "format",
    ["text", "multiline", "markdown", "number", "list", "keyvalue"],
)
def test_validate_definition_accepts_every_editable_field_format(format: str) -> None:
    definition = RuntimeToolDefinition(
        name="editable_field",
        function=_noop,
        description="Supports typed argument editing.",
        presentation=ToolPresentation(
            arg_fields=(
                ToolFieldPresentation(
                    key="value",
                    label="Value",
                    format=format,
                    editable=True,
                ),
            )
        ),
    )

    validate_definition(definition)


def test_validate_definition_accepts_editable_records_columns() -> None:
    definition = RuntimeToolDefinition(
        name="editable_records",
        function=_noop,
        description="Supports declared record rows.",
        presentation=ToolPresentation(
            arg_fields=(
                ToolFieldPresentation(
                    key="rows",
                    label="Rows",
                    format="records",
                    editable=True,
                    columns=(
                        ToolFieldColumn(key="text", label="Keyword", placeholder="Enter keyword"),
                        ToolFieldColumn(
                            key="match_type",
                            label="Match Type",
                            options=("EXACT", "PHRASE", "BROAD"),
                        ),
                    ),
                ),
            )
        ),
    )

    validate_definition(definition)


@pytest.mark.parametrize(
    ("arg_field", "result_field", "error"),
    [
        (
            ToolFieldPresentation(
                key="value",
                label="Value",
                columns=(ToolFieldColumn(key="text", label="Text"),),
            ),
            None,
            "columns require the records format",
        ),
        (
            ToolFieldPresentation(key="rows", label="Rows", format="records"),
            None,
            "Records runtime tool presentation fields require columns",
        ),
        (
            ToolFieldPresentation(
                key="rows",
                label="Rows",
                format="records",
                columns=(
                    ToolFieldColumn(key="text", label="Text"),
                    ToolFieldColumn(key="text", label="Duplicate"),
                ),
            ),
            None,
            "record column keys must be unique",
        ),
        (
            ToolFieldPresentation(
                key="rows",
                label="Rows",
                format="records",
                columns=(ToolFieldColumn(key="Match Type", label="Match Type"),),
            ),
            None,
            "column keys must be lowercase snake_case",
        ),
        (
            ToolFieldPresentation(
                key="rows",
                label="Rows",
                format="records",
                columns=(
                    ToolFieldColumn(
                        key="match_type",
                        label="Match Type",
                        options=("EXACT", " "),
                    ),
                ),
            ),
            None,
            "column options must not be blank",
        ),
        (
            ToolFieldPresentation(
                key="rows",
                label="Rows",
                format="records",
                columns=(
                    ToolFieldColumn(
                        key="match_type",
                        label="Match Type",
                        options=("EXACT", " EXACT "),
                    ),
                ),
            ),
            None,
            "column options must be unique",
        ),
        (
            None,
            ToolFieldPresentation(
                key="rows",
                label="Rows",
                format="records",
                columns=(ToolFieldColumn(key="text", label="Text"),),
            ),
            "result presentation fields cannot use records",
        ),
    ],
)
def test_validate_definition_rejects_invalid_records_presentation(
    arg_field: ToolFieldPresentation | None,
    result_field: ToolFieldPresentation | None,
    error: str,
) -> None:
    definition = RuntimeToolDefinition(
        name="invalid_records",
        function=_noop,
        description="Rejects unsafe record declarations.",
        presentation=ToolPresentation(
            arg_fields=(arg_field,) if arg_field is not None else (),
            result_fields=(result_field,) if result_field is not None else (),
        ),
    )

    with pytest.raises(RuntimeError, match=error):
        validate_definition(definition)


def test_presentation_wire_schema_preserves_typed_field_formats() -> None:
    presentation = ToolPresentation(
        arg_fields=(
            ToolFieldPresentation(
                key="importance",
                label="Importance",
                format="number",
                editable=True,
            ),
            ToolFieldPresentation(
                key="fields",
                label="Fields",
                format="keyvalue",
                editable=True,
            ),
            ToolFieldPresentation(
                key="rows",
                label="Rows",
                format="records",
                editable=True,
                columns=(
                    ToolFieldColumn(key="text", label="Keyword"),
                    ToolFieldColumn(
                        key="match_type",
                        label="Match Type",
                        options=("EXACT", "PHRASE"),
                    ),
                ),
            ),
        )
    )

    serialized = ToolPresentationRead.from_presentation(presentation)

    assert [field.format for field in serialized.arg_fields] == ["number", "keyvalue", "records"]
    assert serialized.arg_fields[0].columns == []
    assert "columns" not in serialized.arg_fields[0].model_dump()
    assert [column.model_dump() for column in serialized.arg_fields[2].columns] == [
        {"key": "text", "label": "Keyword", "options": [], "placeholder": ""},
        {
            "key": "match_type",
            "label": "Match Type",
            "options": ["EXACT", "PHRASE"],
            "placeholder": "",
        },
    ]


def test_presentation_wire_schema_preserves_entity_metadata() -> None:
    presentation = ToolPresentation(
        arg_fields=(
            ToolFieldPresentation(
                key="value",
                label="Record",
                format="entity",
                editable=True,
                entity_kind="airtable_record",
                depends_on=("scope",),
            ),
        )
    )

    serialized = ToolPresentationRead.from_presentation(presentation)

    assert serialized.arg_fields[0].format == "entity"
    assert serialized.arg_fields[0].entity_kind == "airtable_record"
    assert serialized.arg_fields[0].depends_on == ["scope"]


def test_save_memory_editable_options_match_domain_literals() -> None:
    definition = get_runtime_tool_definition("save_memory")
    assert definition.presentation is not None
    fields = {field.key: field for field in definition.presentation.arg_fields}

    assert fields["kind"].options == get_args(MemoryKind.__value__)
    assert fields["scope"].options == get_args(MemoryScope.__value__)
    assert fields["memory_type"].options == get_args(MemoryType.__value__)


def test_google_ads_status_options_match_tool_literal() -> None:
    definition = GOOGLE_ADS_UPDATE_CAMPAIGN_STATUS_DEFINITION
    fields = {field.key: field for field in definition.presentation.arg_fields}
    status_annotation = get_type_hints(
        google_ads_update_campaign_status,
        include_extras=True,
    )["status"]
    status_literal = get_args(status_annotation)[0]

    assert fields["status"].options == get_args(status_literal)


def test_approval_editability_declarations_cover_the_catalog_sweep() -> None:
    integration_definitions = (
        AIRTABLE_CREATE_RECORD_DEFINITION,
        AIRTABLE_GET_RECORD_DEFINITION,
        AIRTABLE_LIST_RECORDS_DEFINITION,
        AIRTABLE_UPDATE_RECORD_DEFINITION,
        BIGQUERY_RUN_QUERY_DEFINITION,
        GMAIL_READ_MESSAGE_DEFINITION,
        GMAIL_SEARCH_MESSAGES_DEFINITION,
        GMAIL_SEND_MESSAGE_DEFINITION,
        GOOGLE_ADS_RUN_REPORT_DEFINITION,
        GOOGLE_ADS_ADD_NEGATIVE_KEYWORDS_DEFINITION,
        GOOGLE_ADS_CREATE_NEGATIVE_KEYWORD_LIST_DEFINITION,
        GOOGLE_ADS_REMOVE_NEGATIVE_KEYWORDS_DEFINITION,
        GOOGLE_ADS_UPDATE_CAMPAIGN_STATUS_DEFINITION,
    )
    definitions = {definition.name: definition for definition in integration_definitions}
    definitions.update(
        {
            name: definition
            for name in {
                "create_artifact",
                "forget_memory",
                "read_document",
                "read_file",
                "save_memory",
                "search_knowledge",
                "update_artifact",
                "update_memory",
            }
            if (definition := get_runtime_tool_definition(name)) is not None
        }
    )
    definitions[DELEGATE_TO_AGENT_DEFINITION.name] = DELEGATE_TO_AGENT_DEFINITION
    expected_editable_fields = {
        "airtable_create_record": {"fields", "table"},
        "airtable_get_record": {"record_id", "table"},
        "airtable_list_records": {
            "filter_by_formula",
            "max_records",
            "table",
            "view",
        },
        "airtable_update_record": {"fields", "record_id", "table"},
        "bigquery_run_query": {"query"},
        "create_artifact": {"content", "title"},
        "delegate_to_agent": {"agent_id", "task"},
        "gmail_read_message": {"message_id"},
        "gmail_search_messages": {"limit", "query"},
        "gmail_send_message": {"bcc", "body_html", "cc", "subject", "to"},
        "google_ads_run_report": {"query"},
        "google_ads_add_negative_keywords": {"keywords", "negative_list"},
        "google_ads_create_negative_keyword_list": {"names"},
        "google_ads_remove_negative_keywords": {"keywords", "negative_list"},
        "google_ads_update_campaign_status": {"campaign_ids", "status"},
        "save_memory": {
            "content",
            "expires_in_days",
            "importance",
            "kind",
            "memory_type",
            "scope",
            "title",
        },
        "read_document": {"document_id"},
        "read_file": {"file_id"},
        "search_knowledge": {"limit", "query"},
        "update_artifact": {"artifact_id", "content", "title"},
        "update_memory": {
            "content",
            "expires_in_days",
            "importance",
            "memory_id",
            "title",
        },
    }

    for tool_name, expected_keys in expected_editable_fields.items():
        definition = definitions[tool_name]
        actual_keys = {field.key for field in definition.presentation.arg_fields if field.editable}
        assert actual_keys == expected_keys, tool_name

    expected_locked_fields = {
        "create_artifact": {"artifact_type"},
        "forget_memory": {"memory_id", "reason"},
        "read_document": {"range"},
        "read_file": {"mode"},
    }
    for tool_name, expected_keys in expected_locked_fields.items():
        definition = definitions[tool_name]
        actual_keys = {
            field.key for field in definition.presentation.arg_fields if not field.editable
        }
        assert actual_keys == expected_keys, tool_name

    format_expectations = {
        ("airtable_create_record", "fields"): "keyvalue",
        ("airtable_list_records", "max_records"): "number",
        ("bigquery_run_query", "query"): "multiline",
        ("create_artifact", "content"): "multiline",
        ("gmail_search_messages", "limit"): "number",
        ("gmail_send_message", "to"): "list",
        ("airtable_get_record", "record_id"): "entity",
        ("airtable_update_record", "record_id"): "entity",
        ("delegate_to_agent", "agent_id"): "entity",
        ("gmail_read_message", "message_id"): "entity",
        ("google_ads_update_campaign_status", "campaign_ids"): "entity_list",
        ("google_ads_add_negative_keywords", "negative_list"): "entity",
        ("google_ads_add_negative_keywords", "keywords"): "records",
        ("google_ads_create_negative_keyword_list", "names"): "list",
        ("google_ads_remove_negative_keywords", "negative_list"): "entity",
        ("google_ads_remove_negative_keywords", "keywords"): "records",
        ("read_document", "document_id"): "entity",
        ("read_file", "file_id"): "entity",
        ("save_memory", "content"): "markdown",
        ("search_knowledge", "limit"): "number",
        ("update_memory", "content"): "markdown",
        ("update_memory", "memory_id"): "entity",
    }
    for (tool_name, field_key), expected_format in format_expectations.items():
        definition = definitions[tool_name]
        fields = {field.key: field for field in definition.presentation.arg_fields}
        assert fields[field_key].format == expected_format

    for tool_name, field_key in {
        ("airtable_list_records", "filter_by_formula"),
        ("airtable_list_records", "max_records"),
        ("airtable_list_records", "view"),
        ("gmail_search_messages", "limit"),
        ("gmail_send_message", "bcc"),
        ("gmail_send_message", "cc"),
        ("save_memory", "expires_in_days"),
        ("search_knowledge", "limit"),
        ("update_memory", "expires_in_days"),
    }:
        definition = definitions[tool_name]
        fields = {field.key: field for field in definition.presentation.arg_fields}
        assert fields[field_key].secondary is True

    report_definition = definitions["google_ads_run_report"]
    assert report_definition.presentation.arg_fields[0].placeholder.startswith("SELECT ")


@pytest.mark.parametrize("icon", ["airtable", "gmail", "google_ads"])
def test_validate_definition_accepts_integration_icon_tokens(icon: str) -> None:
    definition = RuntimeToolDefinition(
        name=f"{icon}_icon_tool",
        function=_noop,
        description="Uses its integration brand mark.",
        presentation=ToolPresentation(icon=icon),
    )

    validate_definition(definition)


def test_allowed_policies_and_tool_build_reject_unsupported_policy() -> None:
    definition = RuntimeToolDefinition(
        name="approval_only",
        function=_noop,
        description="Requires approval.",
        default_policy=TOOL_POLICY_APPROVAL,
        supports_auto=False,
    )

    assert definition.allowed_policies() == frozenset({TOOL_POLICY_APPROVAL})

    with pytest.raises(ModelConfigurationError) as exc_info:
        definition.to_pydantic_tool(policy=TOOL_POLICY_AUTO)

    assert exc_info.value.status_code == 500
    assert exc_info.value.details["tool_name"] == "approval_only"
    assert exc_info.value.details["allowed_tool_policies"] == [TOOL_POLICY_APPROVAL]


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
        "forget_memory",
        "list_files",
        "read_document",
        "read_file",
        "read_todos",
        "save_memory",
        "search_knowledge",
        "search_memory",
        "update_artifact",
        "update_memory",
        "write_file",
        "write_todos",
        "test_runtime_context",
        "test_add_numbers",
    ]
    assert [tool.requires_approval for tool in default_tools] == [
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        True,
        False,
    ]
    assert [tool.timeout for tool in default_tools] == [
        5,
        30,
        15,
        10.0,
        15,
        30.0,
        5,
        15,
        30,
        15,
        30,
        15,
        30.0,
        5,
        5,
        5,
    ]
    assert [tool.max_retries for tool in default_tools] == [
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        1,
    ]
    assert [tool.requires_approval for tool in approved_tools] == [
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        True,
        True,
    ]


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
        "forget_memory",
        "list_files",
        "read_document",
        "read_file",
        "read_todos",
        "save_memory",
        "search_knowledge",
        "search_memory",
        "update_artifact",
        "update_memory",
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


def test_always_allowed_tool_is_mounted_when_workspace_disabled() -> None:
    definition = get_runtime_tool_definition(REPORT_COMPLETION_TOOL_NAME)
    assert definition is not None
    assert definition.always_allowed_when_mounted is True
    assert definition.allowed_policies() == frozenset({TOOL_POLICY_AUTO})

    tools = build_runtime_tools(
        _agent(),
        workspace=object(),
        disabled_tool_names=frozenset({REPORT_COMPLETION_TOOL_NAME}),
        additional_tool_names=(REPORT_COMPLETION_TOOL_NAME,),
    )

    [completion_tool] = [tool for tool in tools if tool.name == REPORT_COMPLETION_TOOL_NAME]
    assert completion_tool.requires_approval is False
