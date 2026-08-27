"""Notion scoped-reference and entity-resolver contracts."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from core.exceptions.integration import IntegrationNotFoundError
from integrations.notion.entity_resolvers.data_source import (
    resolve_notion_data_sources,
    search_notion_data_sources,
)
from integrations.notion.entity_resolvers.page import (
    resolve_notion_pages,
    search_notion_pages,
)
from integrations.notion.references import (
    NotionDataSourceReference,
    NotionPageReference,
)
from services.agents.runtime.untrusted import UntrustedNode
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry


def entry(workspace_id: str) -> ResolvedContextEntry:
    return ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="notion",
        resource_type="notion_workspace",
        external_id=workspace_id,
        display_name=f"Workspace {workspace_id}",
        connection_id=uuid4(),
        connection_label="Notion",
        connection_status="active",
        write_allowed=True,
    )


def context(*entries: ResolvedContextEntry):
    return SimpleNamespace(
        db=object(),
        actor=object(),
        workspace=object(),
        active_context=ResolvedActiveContext(entries=entries),
    )


def page_reference(workspace_id: str, page_id: str = "page-1") -> NotionPageReference:
    return NotionPageReference(
        workspace_id=workspace_id,
        page_id=page_id,
        label="Launch plan",
        scope_label=f"Workspace {workspace_id}",
    )


def data_source_reference(
    workspace_id: str, data_source_id: str = "source-1"
) -> NotionDataSourceReference:
    return NotionDataSourceReference(
        workspace_id=workspace_id,
        data_source_id=data_source_id,
        label="Projects",
        scope_label=f"Workspace {workspace_id}",
    )


def notion_text(content: str, source_ref: str, kind: str) -> UntrustedNode:
    return UntrustedNode(source_kind=kind, source_ref=source_ref, content=content)


@pytest.mark.parametrize("reference_type", [NotionPageReference, NotionDataSourceReference])
def test_references_reject_bare_uuid_strings(reference_type) -> None:
    with pytest.raises(ValidationError):
        reference_type.model_validate(str(uuid4()))


def test_page_reference_rejects_data_source_reference() -> None:
    with pytest.raises(ValidationError):
        NotionPageReference.model_validate(data_source_reference("workspace-1").model_dump())


def test_reference_identity_uses_provider_scope_and_entity() -> None:
    page = page_reference("workspace-1")
    data_source = data_source_reference("workspace-1")

    assert page.provider_scope_id == "workspace-1"
    assert page.provider_entity_id == "page-1"
    assert page.identity()[-2:] == ("workspace-1", "page-1")
    assert data_source.provider_scope_id == "workspace-1"
    assert data_source.provider_entity_id == "source-1"


async def test_page_search_fans_out_and_pages_with_offset(monkeypatch) -> None:
    entries = (entry("workspace-1"), entry("workspace-2"))

    async def client_for_principal(*_args, entry, **_kwargs):
        return entry.external_id

    async def search(client, **_kwargs):
        return {
            "items": [
                {
                    "kind": "page",
                    "id": f"{client}-page-{index}",
                    "title": notion_text(f"Plan {index}", f"{client}-page-{index}", "notion_page"),
                    "url": "https://www.notion.so/page",
                    "last_edited_time": "2026-08-25T12:00:00Z",
                }
                for index in range(3)
            ]
        }

    monkeypatch.setattr(
        "integrations.notion.entity_resolvers.utils.notion_client_for_principal",
        client_for_principal,
    )
    monkeypatch.setattr("integrations.notion.entity_resolvers.utils.search_notion", search)

    first = await search_notion_pages(context(*entries), "plan", {}, 2, None)
    second = await search_notion_pages(context(*entries), "plan", {}, 2, first.next_cursor)

    assert [choice.value["workspace_id"] for choice in first.choices] == [
        "workspace-1",
        "workspace-1",
    ]
    assert [choice.value["workspace_id"] for choice in second.choices] == [
        "workspace-1",
        "workspace-2",
    ]
    assert all(choice.icon == "notion" for choice in (*first.choices, *second.choices))


async def test_data_source_search_uses_matching_object_filter(monkeypatch) -> None:
    selected = entry("workspace-1")
    calls: list[dict] = []

    async def client_for_principal(*_args, **_kwargs):
        return object()

    async def search(_client, **kwargs):
        calls.append(kwargs)
        return {
            "items": [
                {
                    "kind": "data_source",
                    "id": "source-1",
                    "title": notion_text("Projects", "source-1", "notion_data_source"),
                    "url": "https://www.notion.so/source",
                    "last_edited_time": "2026-08-25T12:00:00Z",
                }
            ]
        }

    monkeypatch.setattr(
        "integrations.notion.entity_resolvers.utils.notion_client_for_principal",
        client_for_principal,
    )
    monkeypatch.setattr("integrations.notion.entity_resolvers.utils.search_notion", search)

    result = await search_notion_data_sources(context(selected), "projects", {}, 20, None)

    assert calls[0]["kind"] == "data_source"
    assert result.choices[0].value["data_source_id"] == "source-1"


async def test_exact_resolution_uses_only_the_matching_workspace(monkeypatch) -> None:
    first = entry("workspace-1")
    second = entry("workspace-2")
    clients: list[str] = []

    async def client_for_principal(*_args, entry, **_kwargs):
        clients.append(entry.external_id)
        return entry.external_id

    async def get_page(_client, *, page_id):
        return {
            "id": page_id,
            "title": notion_text("Hydrated", page_id, "notion_page"),
            "url": "https://www.notion.so/page",
            "last_edited_time": "2026-08-25T12:00:00Z",
        }

    monkeypatch.setattr(
        "integrations.notion.entity_resolvers.utils.notion_client_for_principal",
        client_for_principal,
    )
    monkeypatch.setattr("integrations.notion.entity_resolvers.page.get_page", get_page)

    choices = await resolve_notion_pages(
        context(first, second),
        [page_reference("workspace-2").model_dump(), page_reference("missing").model_dump()],
        {},
    )

    assert clients == ["workspace-2"]
    assert len(choices) == 1
    assert choices[0].label == "Hydrated"


async def test_exact_resolution_omits_not_found_and_wrong_reference_types(monkeypatch) -> None:
    selected = entry("workspace-1")

    async def client_for_principal(*_args, **_kwargs):
        return object()

    async def get_data_source(_client, *, data_source_id):
        raise IntegrationNotFoundError(
            "Notion resource was not found",
            provider_key="notion",
            operation="get_data_source",
        )

    monkeypatch.setattr(
        "integrations.notion.entity_resolvers.utils.notion_client_for_principal",
        client_for_principal,
    )
    monkeypatch.setattr(
        "integrations.notion.entity_resolvers.data_source.get_data_source",
        get_data_source,
    )

    choices = await resolve_notion_data_sources(
        context(selected),
        [
            data_source_reference("workspace-1").model_dump(),
            page_reference("workspace-1").model_dump(),
        ],
        {},
    )

    assert choices == ()
