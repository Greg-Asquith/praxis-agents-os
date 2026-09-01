# apps/api/tests/integrations/notion/test_notion_write_tools.py

"""Approval, audit, and presentation contracts for Notion write tools."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError
from pydantic_ai import ModelRetry

from core.exceptions.integration import (
    IntegrationFailureDisposition,
    IntegrationTimeoutError,
)
from integrations.notion.operations.create_page import CreatePagePreparation
from integrations.notion.operations.properties import NotionMutationTarget
from integrations.notion.operations.update_page_markdown import (
    UpdatePageMarkdownPreparation,
)
from integrations.notion.operations.update_page_properties import (
    UpdatePagePropertiesPreparation,
)
from integrations.notion.references import (
    NotionDataSourceReference,
    NotionPageReference,
)
from integrations.notion.tools import TOOL_DEFINITIONS
from integrations.notion.tools.create_page import NotionPageTitle, notion_create_page
from integrations.notion.tools.mutations import (
    NotionPropertyRecord,
    NotionReplacementRecord,
)
from integrations.notion.tools.schemas import (
    NotionCreatePageOutput,
    NotionUpdatePageContentOutput,
    NotionUpdatePagePropertiesOutput,
)
from integrations.notion.tools.update_page_content import notion_update_page_content
from integrations.notion.tools.update_page_properties import notion_update_page_properties
from services.agent_runs.validate_override_args import validate_and_canonicalize_override_args
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_EXTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_EXTERNAL_WRITE,
    TOOL_POLICY_APPROVAL,
    validate_definition,
)
from services.audit_events import AuditStatus
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry


def _entry(*, workspace_id: str = "workspace-1", write_allowed: bool = True):
    return ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="notion",
        resource_type="notion_workspace",
        external_id=workspace_id,
        display_name="Product workspace",
        connection_id=uuid4(),
        connection_label="Product",
        connection_status="active",
        write_allowed=write_allowed,
    )


def _context(tool_name: str, entry: ResolvedContextEntry):
    return SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(entry,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name=tool_name,
        tool_call_id=f"call-{tool_name}",
    )


def _page_reference(workspace_id: str = "workspace-1") -> NotionPageReference:
    return NotionPageReference(
        workspace_id=workspace_id,
        page_id="page-1",
        label="Launch plan",
        description="Notion page",
        scope_label="Product workspace",
    )


def _data_source_reference() -> NotionDataSourceReference:
    return NotionDataSourceReference(
        workspace_id="workspace-1",
        data_source_id="data-source-1",
        label="Projects",
        description="Notion data source",
        scope_label="Product workspace",
    )


def _target(
    *,
    entity_type: str = "notion_page",
    external_id: str = "page-1",
    display_name: str = "Launch plan",
    property_types: dict[str, str] | None = None,
) -> NotionMutationTarget:
    return NotionMutationTarget(
        entity_type=entity_type,
        external_id=external_id,
        display_name=display_name,
        property_types=property_types or {},
    )


def _audit(monkeypatch) -> AsyncMock:
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )
    return audit


def test_notion_write_definitions_are_approval_only_and_losslessly_presented() -> None:
    definitions = {definition.name: definition for definition in TOOL_DEFINITIONS}
    writes = {
        name: definitions[name]
        for name in (
            "notion_create_page",
            "notion_update_page_content",
            "notion_update_page_properties",
        )
    }
    for definition in writes.values():
        validate_definition(definition)
        assert definition.effect == TOOL_EFFECT_WRITE
        assert definition.effect_scope == TOOL_EFFECT_SCOPE_EXTERNAL
        assert definition.egress == TOOL_EGRESS_EXTERNAL_WRITE
        assert definition.default_policy == TOOL_POLICY_APPROVAL
        assert definition.supports_auto is False
        assert definition.supports_approval is True
        assert definition.allowed_policies() == frozenset({TOOL_POLICY_APPROVAL})
        assert definition.code_eligible is True
        assert definition.takes_ctx is True
        assert definition.timeout == 90
        assert definition.integration_binding is not None
        assert definition.integration_binding.requires_write is True

    create_fields = {
        field.key: field for field in writes["notion_create_page"].presentation.arg_fields
    }
    assert create_fields["parent_page"].entity_kind == "notion_page"
    assert create_fields["parent_page"].secondary is True
    assert create_fields["parent_data_source"].entity_kind == "notion_data_source"
    assert create_fields["parent_data_source"].secondary is True
    assert create_fields["content_md"].format == "markdown"
    assert create_fields["properties"].min_rows == 0

    replacement_field = next(
        field
        for field in writes["notion_update_page_content"].presentation.arg_fields
        if field.key == "replacements"
    )
    assert replacement_field.min_rows == 1
    assert [column.key for column in replacement_field.columns] == [
        "old_text",
        "new_text",
        "replace_all",
    ]
    assert replacement_field.columns[2].options == ("no", "yes")

    property_field = next(
        field
        for field in writes["notion_update_page_properties"].presentation.arg_fields
        if field.key == "properties"
    )
    assert property_field.min_rows == 1
    assert [column.key for column in property_field.columns] == ["name", "type", "value"]
    assert property_field.columns[1].options == (
        "title",
        "rich_text",
        "number",
        "checkbox",
        "url",
        "email",
        "phone_number",
        "date",
        "select",
        "status",
        "multi_select",
    )


def test_create_page_title_contract_normalizes_and_validates_before_approval() -> None:
    adapter = TypeAdapter(NotionPageTitle)

    assert adapter.validate_python("  Launch notes  ") == "Launch notes"
    with pytest.raises(ValidationError, match="at least 1 character"):
        adapter.validate_python("   ")
    with pytest.raises(ValidationError, match="at most 500 characters"):
        adapter.validate_python("x" * 501)


@pytest.mark.parametrize("properties", [None, []])
async def test_create_page_approval_accepts_optional_properties(monkeypatch, properties) -> None:
    definition = next(
        definition for definition in TOOL_DEFINITIONS if definition.name == "notion_create_page"
    )
    monkeypatch.setattr(
        "services.agents.runtime.tools.registry.get_runtime_tool_definition",
        lambda _tool_name: definition,
    )
    reference = _page_reference().model_dump(mode="json")
    authorize = AsyncMock(return_value=SimpleNamespace())
    resolve = AsyncMock(return_value=[reference])
    monkeypatch.setattr(
        "services.agents.runtime.entity_references.service.authorize_entity_field",
        authorize,
    )
    monkeypatch.setattr(
        "services.agents.runtime.entity_references.service.resolve_authorized_references",
        resolve,
    )
    args = {"title": "Launch notes", "parent_page": reference}
    if properties is not None:
        args["properties"] = properties

    result = await validate_and_canonicalize_override_args(
        AsyncMock(),
        actor=SimpleNamespace(),
        workspace=SimpleNamespace(),
        membership=SimpleNamespace(),
        run=SimpleNamespace(conversation_id=uuid4()),
        tool_call=SimpleNamespace(tool_name="notion_create_page", args=args),
        override_args=None,
    )

    assert result is None
    authorize.assert_awaited_once()
    resolve.assert_awaited_once()


@pytest.mark.parametrize(
    ("parent_page", "parent_data_source"),
    [
        (None, None),
        (_page_reference(), _data_source_reference()),
    ],
)
async def test_create_page_rejects_zero_or_two_parents(
    parent_page: NotionPageReference | None,
    parent_data_source: NotionDataSourceReference | None,
) -> None:
    with pytest.raises(ModelRetry, match="Choose one Notion page or data source"):
        await notion_create_page(
            _context("notion_create_page", _entry()),
            title="Launch notes",
            parent_page=parent_page,
            parent_data_source=parent_data_source,
        )


async def test_create_page_records_one_pending_and_terminal_event(monkeypatch) -> None:
    entry = _entry()
    audit = _audit(monkeypatch)
    prepared = CreatePagePreparation(
        parent=_target(),
        parent_type="page_id",
        title="Launch notes",
        content_md="# Launch\n",
        property_count=0,
        properties={"title": {"title": []}},
    )
    monkeypatch.setattr(
        "integrations.notion.tools.create_page.notion_client",
        AsyncMock(return_value=object()),
    )
    prepare = AsyncMock(return_value=prepared)
    monkeypatch.setattr("integrations.notion.tools.create_page.prepare_create_page", prepare)
    monkeypatch.setattr(
        "integrations.notion.tools.create_page.create_page",
        AsyncMock(
            return_value={
                "id": "page-2",
                "url": "https://www.notion.so/page-2",
                "title": "Launch notes",
                "last_edited_time": "2026-09-01T12:00:00.000Z",
            }
        ),
    )

    result = await notion_create_page(
        _context("notion_create_page", entry),
        title="Launch notes",
        parent_page=_page_reference(),
        content_md="# Launch\n",
    )

    NotionCreatePageOutput.model_validate(result)
    assert result["results"][0]["data"]["reference"].page_id == "page-2"
    assert [call.kwargs["status"] for call in audit.await_args_list] == [
        AuditStatus.PENDING,
        AuditStatus.SUCCESS,
    ]
    assert audit.await_args_list[1].kwargs["external_ref"] == "page-2"
    prepare.assert_awaited_once()


async def test_content_update_records_exact_edited_arguments(monkeypatch) -> None:
    entry = _entry()
    audit = _audit(monkeypatch)
    replacements = [
        NotionReplacementRecord(
            old_text="Draft launch plan",
            new_text="Approved launch plan",
            replace_all="yes",
        )
    ]
    prepared = UpdatePageMarkdownPreparation(
        page=_target(),
        replacements=tuple(replacements),
    )
    monkeypatch.setattr(
        "integrations.notion.tools.update_page_content.notion_client",
        AsyncMock(return_value=object()),
    )
    prepare = AsyncMock(return_value=prepared)
    monkeypatch.setattr(
        "integrations.notion.tools.update_page_content.prepare_update_page_markdown",
        prepare,
    )
    monkeypatch.setattr(
        "integrations.notion.tools.update_page_content.update_page_markdown",
        AsyncMock(
            return_value={
                "id": "page-1",
                "applied_replacements": 1,
                "page_truncated": False,
                "last_edited_time": "2026-09-01T12:00:00.000Z",
            }
        ),
    )

    result = await notion_update_page_content(
        _context("notion_update_page_content", entry),
        _page_reference(),
        replacements,
    )

    NotionUpdatePageContentOutput.model_validate(result)
    prepare.assert_awaited_once_with(
        prepare.await_args.args[0],
        entry,
        page=_page_reference(),
        replacements=replacements,
    )
    pending = audit.await_args_list[0].kwargs["operation_detail"]
    assert pending.intent_groups[0].items[0].fields == {
        "old_text": "Draft launch plan",
        "new_text": "Approved launch plan",
        "old_text_length": 17,
        "new_text_length": 20,
        "replace_all": "yes",
    }
    assert audit.await_args_list[1].kwargs["external_ref"] == "page-1"


async def test_property_update_retains_unverified_result_after_timeout(monkeypatch) -> None:
    entry = _entry()
    audit = _audit(monkeypatch)
    properties = [NotionPropertyRecord(name="Status", type="status", value="Done")]
    prepared = UpdatePagePropertiesPreparation(
        page=_target(property_types={"Status": "status"}),
        records=tuple(properties),
        properties={"Status": {"status": {"name": "Done"}}},
    )
    monkeypatch.setattr(
        "integrations.notion.tools.update_page_properties.notion_client",
        AsyncMock(return_value=object()),
    )
    prepare = AsyncMock(return_value=prepared)
    monkeypatch.setattr(
        "integrations.notion.tools.update_page_properties.prepare_update_page_properties",
        prepare,
    )
    monkeypatch.setattr(
        "integrations.notion.tools.update_page_properties.update_page_properties",
        AsyncMock(
            side_effect=IntegrationTimeoutError(
                "Private provider message",
                provider_key="notion",
                operation="update_page_properties",
                failure_disposition=IntegrationFailureDisposition.AMBIGUOUS,
            )
        ),
    )

    result = await notion_update_page_properties(
        _context("notion_update_page_properties", entry),
        _page_reference(),
        properties,
    )

    NotionUpdatePagePropertiesOutput.model_validate(result)
    item = result["results"][0]
    assert item["status"] == "error"
    assert item["error_code"] == "unverified_mutation"
    assert item["data"]["outcome"] == "unverified"
    assert item["data"]["error_code"] == "timeout"
    assert "Private provider message" not in str(item["data"])
    assert [call.kwargs["status"] for call in audit.await_args_list] == [
        AuditStatus.PENDING,
        AuditStatus.UNVERIFIED,
    ]
    terminal = audit.await_args_list[1].kwargs["operation_detail"]
    assert terminal.intent_counts.unverified == terminal.effect_counts.unverified == 1


async def test_read_only_resource_records_denial_without_provider_call(monkeypatch) -> None:
    entry = _entry(write_allowed=False)
    provider = AsyncMock()
    denial = AsyncMock()
    monkeypatch.setattr(
        "integrations.notion.tools.update_page_properties.notion_client",
        provider,
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_write_denial",
        denial,
    )

    result = await notion_update_page_properties(
        _context("notion_update_page_properties", entry),
        _page_reference(),
        [NotionPropertyRecord(name="Status", type="status", value="Done")],
    )

    provider.assert_not_awaited()
    denial.assert_awaited_once()
    assert result["results"][0]["error_code"] == "write_not_permitted"
