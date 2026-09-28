# apps/api/tests/integrations/notion/test_notion_write_tools.py

"""Approval, audit, and presentation contracts for Notion write tools."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

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
    NotionPageReference,
)
from integrations.notion.tools.create_page import notion_create_page
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
