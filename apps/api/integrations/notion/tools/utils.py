# apps/api/integrations/notion/tools/utils.py

"""Shared Notion tool binding and credential access."""

from pydantic_ai import ModelRetry, RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    IntegrationToolBinding,
    ToolFieldPresentation,
)
from services.audit_events import (
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    IntegrationOperationTarget,
    PendingIntegrationOperationDetail,
)
from services.integrations.connections.utils import refresh_oauth_credential
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import (
    IntegrationContextResult,
    serialize_fan_out_results,
)
from services.integrations.credentials import (
    ensure_fresh_credential,
    get_usable_connection_credential,
)

from ..client import NotionClient
from ..operations.create_page import CreatePagePreparation
from ..operations.properties import NotionMutationTarget
from ..operations.update_page_markdown import UpdatePageMarkdownPreparation
from ..operations.update_page_properties import UpdatePagePropertiesPreparation
from ..operations.utils import serialized_json_bytes
from ..settings import notion_settings

NOTION_BINDING = IntegrationToolBinding(
    provider_keys=frozenset({"notion"}),
    resource_types=frozenset({"notion_workspace"}),
)
NOTION_WRITE_BINDING = IntegrationToolBinding(
    provider_keys=NOTION_BINDING.provider_keys,
    resource_types=NOTION_BINDING.resource_types,
    requires_write=True,
)
RESULTS_FIELD = (ToolFieldPresentation(key="results", label="Workspaces", format="list"),)
MAX_NOTION_RESULT_BYTES = 768 * 1024


def bounded_notion_output(results: list[IntegrationContextResult]) -> dict[str, object]:
    """Returns a Notion result only when its complete serialized value is bounded."""
    output: dict[str, object] = {"results": serialize_fan_out_results(results)}
    if serialized_json_bytes(output) > MAX_NOTION_RESULT_BYTES:
        raise ModelRetry("Notion returned too much data. Retry with a lower maximum result count.")
    return output


async def notion_client(
    ctx: RunContext[RuntimeDeps],
    entry: ResolvedContextEntry,
) -> NotionClient:
    return await notion_client_for_principal(
        ctx.deps.db,
        actor=ctx.deps.user,
        workspace=ctx.deps.workspace,
        entry=entry,
    )


async def notion_client_for_principal(
    db, *, actor, workspace, entry: ResolvedContextEntry
) -> NotionClient:
    async def access_token(force: bool) -> str:
        usable = await get_usable_connection_credential(
            db,
            connection_id=entry.connection_id,
            actor=actor,
            workspace=workspace,
        )
        credential = await ensure_fresh_credential(
            db,
            credential_id=usable.id,
            refresh_token=refresh_oauth_credential,
            force=force,
        )
        token = credential.access_token
        if not token:
            raise ModelRetry("The Notion connection needs to be reconnected.")
        return token

    return NotionClient(access_token, pacing_key=str(entry.connection_id))


def notion_available() -> bool:
    return bool(notion_settings.NOTION_OAUTH_CLIENT_ID.strip())


def notion_page_target(
    entry: ResolvedContextEntry,
    page: NotionMutationTarget,
) -> IntegrationOperationTarget:
    """Builds the provider page target used by Notion write evidence."""
    return _notion_target(entry, page)


def pending_create_page_detail(
    entry: ResolvedContextEntry,
    prepared: CreatePagePreparation,
) -> PendingIntegrationOperationDetail:
    """Builds bounded intent for one page creation."""
    return PendingIntegrationOperationDetail(
        target=_notion_target(entry, prepared.parent),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key="page:create",
                action="create_page",
                entity_type="notion_page",
                items=[
                    IntegrationOperationIntent(
                        fields={
                            "title": prepared.title,
                            "content_bytes": len(prepared.content_md.encode("utf-8")),
                            "property_count": prepared.property_count,
                        }
                    )
                ],
            )
        ],
    )


def pending_update_content_detail(
    entry: ResolvedContextEntry,
    prepared: UpdatePageMarkdownPreparation,
) -> PendingIntegrationOperationDetail:
    """Builds bounded intent for exact-text page replacements."""
    return PendingIntegrationOperationDetail(
        target=notion_page_target(entry, prepared.page),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key=f"page:{prepared.page.external_id}:content",
                action="update_content",
                entity_type="notion_page",
                external_id=prepared.page.external_id,
                display_name=prepared.page.display_name,
                items=[
                    IntegrationOperationIntent(
                        fields={
                            "old_text": record.old_text[:1_000],
                            "new_text": record.new_text[:1_000],
                            "old_text_length": len(record.old_text),
                            "new_text_length": len(record.new_text),
                            "replace_all": record.replace_all,
                        }
                    )
                    for record in prepared.replacements
                ],
            )
        ],
    )


def pending_update_properties_detail(
    entry: ResolvedContextEntry,
    prepared: UpdatePagePropertiesPreparation,
) -> PendingIntegrationOperationDetail:
    """Builds bounded intent for schema-validated page properties."""
    return PendingIntegrationOperationDetail(
        target=notion_page_target(entry, prepared.page),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key=f"page:{prepared.page.external_id}:properties",
                action="update_properties",
                entity_type="notion_page",
                external_id=prepared.page.external_id,
                display_name=prepared.page.display_name,
                items=[
                    IntegrationOperationIntent(
                        fields={
                            "name": record.name,
                            "type": record.type,
                            "value": record.value[:1_000],
                        }
                    )
                    for record in prepared.records
                ],
            )
        ],
    )


def _notion_target(
    entry: ResolvedContextEntry,
    target: NotionMutationTarget,
) -> IntegrationOperationTarget:
    return IntegrationOperationTarget(
        entity_type=target.entity_type,
        external_id=target.external_id,
        display_name=target.display_name,
        integration_resource_id=str(entry.integration_resource_id),
    )
