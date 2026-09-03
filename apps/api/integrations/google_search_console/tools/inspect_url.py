# apps/api/integrations/google_search_console/tools/inspect_url.py

"""Inspect URLs against their selected Search Console properties."""

from collections import Counter
from collections.abc import Sequence
from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import RunContext

from core.exceptions.integration import IntegrationError
from integrations.google_search_console.references import (
    MAX_SEARCH_CONSOLE_URL_LENGTH,
    GoogleSearchConsoleUrlReference,
)
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_EGRESS_PROVIDER_QUERY,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.audit_events import AuditStatus
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.context.targeted import run_context_targets
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)
from services.integrations.read_audit import read_operation_detail

from ..operations.inspect_url import inspect_url
from .schemas import GoogleSearchConsoleInspectUrlOutput
from .utils.bindings import GOOGLE_SEARCH_CONSOLE_BINDING, RESULTS_FIELD
from .utils.client import google_search_console_available, google_search_console_client
from .utils.routing import url_references_for_entries


async def google_search_console_inspect_url(
    ctx: RunContext[RuntimeDeps],
    urls: Annotated[
        list[Annotated[str, Field(max_length=MAX_SEARCH_CONSOLE_URL_LENGTH)]],
        Field(
            min_length=1,
            max_length=10,
            description="HTTP or HTTPS URLs to inspect, with no duplicates.",
        ),
    ],
    language_code: Annotated[
        str,
        Field(
            min_length=2,
            max_length=35,
            pattern=r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$",
            description="BCP-47 language code for translated issue messages.",
        ),
    ] = "en-US",
) -> dict[str, Any]:
    active_context = ctx.deps.active_context
    entries = (
        active_context.compatible_entries(GOOGLE_SEARCH_CONSOLE_BINDING)
        if active_context is not None
        else ()
    )
    references = url_references_for_entries(entries, urls)

    async def operation(
        entry: ResolvedContextEntry,
        scoped_references: Sequence[GoogleSearchConsoleUrlReference],
    ) -> Any:
        async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
            client = await google_search_console_client(ctx, entry)
            inspections = [
                await inspect_url(
                    client,
                    site_url=entry.external_id,
                    url=reference.url,
                    language_code=language_code,
                )
                for reference in scoped_references
            ]
            if all(item["error_code"] is not None for item in inspections):
                raise IntegrationError(
                    "Google Search Console could not inspect any requested URLs for this site.",
                    provider_key="google_search_console",
                    operation="inspect_url",
                )
            verdict_counts = Counter(
                _audit_verdict(item["verdict"]) if item["error_code"] is None else "provider_error"
                for item in inspections
            )
            audit_status = (
                AuditStatus.PARTIAL if verdict_counts["provider_error"] else AuditStatus.SUCCESS
            )
            result = {"inspections": inspections}
            return IntegrationAuditOutcome(
                result,
                status=audit_status,
                operation_detail=read_operation_detail(
                    entry,
                    operation="inspect_url",
                    target_entity_type="google_search_console_site",
                    entity_type="google_search_console_url",
                    status=audit_status,
                    fields={
                        "url_count": len(inspections),
                        "verdict_counts": dict(sorted(verdict_counts.items())),
                    },
                ),
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_search_console_inspect_url",
            operation="inspect_url",
            execute=execute,
        )

    results = await run_context_targets(
        ctx,
        binding=GOOGLE_SEARCH_CONSOLE_BINDING,
        references=references,
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


def _audit_verdict(value: str) -> str:
    normalized = value.strip().upper()
    return normalized.lower() if normalized in {"PASS", "FAIL", "NEUTRAL", "PARTIAL"} else "unknown"


DEFINITION = RuntimeToolDefinition(
    name="google_search_console_inspect_url",
    function=google_search_console_inspect_url,
    description=(
        "Inspect only URLs the user asked about against their selected Google Search Console "
        "properties. Each call accepts up to 10 URLs, routes each URL to the most specific "
        "selected property, and reports Google's indexed version rather than a live test. "
        "Google limits URL Inspection to 2,000 requests per property per day."
    ),
    provider="google_search_console",
    label="Inspect Search Console URLs",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    takes_ctx=True,
    timeout=60,
    output_model=GoogleSearchConsoleInspectUrlOutput,
    integration_binding=GOOGLE_SEARCH_CONSOLE_BINDING,
    availability_check=google_search_console_available,
    presentation=ToolPresentation(
        icon="google_search_console",
        running_label="Inspecting Search Console URLs",
        completed_label="Inspected Search Console URLs",
        failed_label="Couldn't Inspect Search Console URLs",
        arg_fields=(
            ToolFieldPresentation(key="urls", label="URLs", format="list"),
            ToolFieldPresentation(key="language_code", label="Language", format="text"),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
