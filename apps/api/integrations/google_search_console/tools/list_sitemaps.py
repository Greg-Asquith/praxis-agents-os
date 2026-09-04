# apps/api/integrations/google_search_console/tools/list_sitemaps.py

"""List sitemap status for selected Search Console sites."""

from typing import Any

from pydantic_ai import RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_EGRESS_PROVIDER_QUERY,
    RuntimeToolDefinition,
    ToolPresentation,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.fan_out import run_context_fan_out
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)
from services.integrations.read_audit import read_operation_detail

from ..operations.list_sitemaps import list_sitemaps
from .schemas import GoogleSearchConsoleListSitemapsOutput
from .utils.bindings import GOOGLE_SEARCH_CONSOLE_BINDING, RESULTS_FIELD
from .utils.client import google_search_console_client


async def google_search_console_list_sitemaps(
    ctx: RunContext[RuntimeDeps],
) -> dict[str, Any]:
    async def operation(entry: ResolvedContextEntry) -> Any:
        async def execute() -> Any:
            client = await google_search_console_client(ctx, entry)
            result = await list_sitemaps(client, site_url=entry.external_id)
            return IntegrationAuditOutcome(
                result,
                operation_detail=read_operation_detail(
                    entry,
                    operation="list_sitemaps",
                    target_entity_type="google_search_console_site",
                    entity_type="google_search_console_sitemap",
                    fields={"sitemap_count": int(result["sitemap_count"])},
                ),
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_search_console_list_sitemaps",
            operation="list_sitemaps",
            execute=execute,
        )

    results = await run_context_fan_out(
        ctx,
        binding=GOOGLE_SEARCH_CONSOLE_BINDING,
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


DEFINITION = RuntimeToolDefinition(
    name="google_search_console_list_sitemaps",
    function=google_search_console_list_sitemaps,
    description=(
        "List up to 200 submitted sitemaps for every Google Search Console site selected in "
        "Active Context. Results are sorted by the latest submission and include processing, "
        "warning, error, sitemap-index, and submitted URL counts."
    ),
    provider="google_search_console",
    label="List Search Console Sitemaps",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    takes_ctx=True,
    timeout=60,
    output_model=GoogleSearchConsoleListSitemapsOutput,
    integration_binding=GOOGLE_SEARCH_CONSOLE_BINDING,
    presentation=ToolPresentation(
        icon="google_search_console",
        running_label="Listing Search Console Sitemaps",
        completed_label="Listed Search Console Sitemaps",
        failed_label="Couldn't List Search Console Sitemaps",
        result_fields=RESULTS_FIELD,
    ),
)
