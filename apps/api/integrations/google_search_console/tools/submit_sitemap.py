# apps/api/integrations/google_search_console/tools/submit_sitemap.py

"""Submit Search Console sitemaps through an approval-gated audited mutation."""

import asyncio
from collections.abc import Mapping, Sequence
from functools import partial
from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import RunContext, ToolReturn

from core.exceptions.integration import IntegrationError, IntegrationFailureDisposition
from integrations.google_search_console.client import GoogleSearchConsoleClient
from integrations.google_search_console.references import (
    MAX_SEARCH_CONSOLE_URL_LENGTH,
    GoogleSearchConsoleUrlReference,
)
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_EXTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_EXTERNAL_WRITE,
    TOOL_POLICY_APPROVAL,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.audit_events import AuditStatus, PendingIntegrationOperationDetail
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import split_fan_out_tool_return
from services.integrations.context.targeted import run_context_targets
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.get_sitemap import get_sitemap
from ..operations.submit_sitemap import submit_sitemap
from .schemas import GoogleSearchConsoleSubmitSitemapsOutput
from .utils import sitemap_submission_results
from .utils.bindings import GOOGLE_SEARCH_CONSOLE_WRITE_BINDING, RESULTS_FIELD
from .utils.client import (
    google_search_console_client,
    google_search_console_client_for_principal,
)
from .utils.mutation_evidence import audit_status, sitemap_pending_detail, sitemap_terminal_detail
from .utils.routing import sitemap_references_for_entries

MAX_SITEMAPS_PER_SUBMISSION = 20
MAX_SITEMAP_RESULT_CHARS = 120_000
MAX_SITEMAP_PUBLIC_RESULT_CHARS = 160_000


async def google_search_console_submit_sitemap(
    ctx: RunContext[RuntimeDeps],
    sitemap_urls: Annotated[
        list[Annotated[str, Field(max_length=MAX_SEARCH_CONSOLE_URL_LENGTH)]],
        Field(
            min_length=1,
            max_length=MAX_SITEMAPS_PER_SUBMISSION,
            description="Absolute HTTP or HTTPS sitemap URLs to submit, with no duplicates.",
        ),
    ],
) -> ToolReturn[dict[str, Any]]:
    active_context = ctx.deps.active_context
    entries = (
        active_context.compatible_entries(GOOGLE_SEARCH_CONSOLE_WRITE_BINDING)
        if active_context is not None
        else ()
    )
    references = sitemap_references_for_entries(entries, sitemap_urls)

    results = await run_context_targets(
        ctx,
        binding=GOOGLE_SEARCH_CONSOLE_WRITE_BINDING,
        references=references,
        operation=partial(_submit_sitemaps_for_entry, ctx),
    )
    return split_fan_out_tool_return(results)


async def _submit_sitemaps_for_entry(
    ctx: RunContext[RuntimeDeps],
    entry: ResolvedContextEntry,
    scoped_references: Sequence[GoogleSearchConsoleUrlReference],
) -> Any:
    client: GoogleSearchConsoleClient | None = None
    prepared: list[dict[str, Any]] = []
    pending: PendingIntegrationOperationDetail | None = None

    async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
        nonlocal client, pending, prepared
        client = await google_search_console_client(ctx, entry)
        prepared = await _prepare_sitemaps(client, entry, scoped_references)
        pending = sitemap_pending_detail(entry, prepared)
        return pending

    async def execute() -> IntegrationAuditOutcome[dict[str, dict[str, Any]]]:
        if client is None or pending is None or not prepared:
            raise RuntimeError("Sitemap submission preparation did not complete")
        return await _execute_submission(client, entry, pending, prepared)

    return await run_audited_integration_operation(
        ctx,
        entry,
        tool_name="google_search_console_submit_sitemap",
        operation="submit_sitemap",
        execute=execute,
        prepare_pending_operation=prepare_pending_operation,
    )


async def _execute_submission(
    client: GoogleSearchConsoleClient,
    entry: ResolvedContextEntry,
    pending: PendingIntegrationOperationDetail,
    prepared: Sequence[Mapping[str, Any]],
) -> IntegrationAuditOutcome[dict[str, dict[str, Any]]]:
    outcomes: list[dict[str, Any]] = []
    for item in prepared:
        try:
            await submit_sitemap(
                client,
                site_url=entry.external_id,
                sitemap_url=item["sitemap_url"],
            )
        except asyncio.CancelledError as exc:
            _attach_cancellation_evidence(exc, pending, prepared, outcomes, item)
            raise
        except IntegrationError as exc:
            outcomes.append(_failed_outcome(item, exc))
            continue
        except Exception as exc:
            _attach_interruption_evidence(
                exc,
                pending,
                prepared,
                outcomes,
                item,
                default_disposition=IntegrationFailureDisposition.AMBIGUOUS,
            )
            raise

        try:
            status = await get_sitemap(
                client,
                site_url=entry.external_id,
                sitemap_url=item["sitemap_url"],
            )
        except asyncio.CancelledError as exc:
            outcomes.append(_submitted_outcome(item, None))
            _attach_cancellation_evidence(exc, pending, prepared, outcomes, None)
            raise
        except IntegrationError:
            status = None
        except Exception as exc:
            outcomes.append(_submitted_outcome(item, None))
            _attach_interruption_evidence(
                exc,
                pending,
                prepared,
                outcomes,
                None,
                default_disposition=IntegrationFailureDisposition.REJECTED,
            )
            raise
        outcomes.append(_submitted_outcome(item, status))

    terminal = sitemap_terminal_detail(pending, outcomes)
    status = audit_status(terminal)
    result = sitemap_submission_results(outcomes)
    return IntegrationAuditOutcome(
        result,
        status=status,
        external_ref=",".join(str(item["sitemap_url"]) for item in prepared),
        operation_detail=terminal,
        unverified_result=result if status is AuditStatus.UNVERIFIED else None,
    )


async def _prepare_sitemaps(
    client: GoogleSearchConsoleClient,
    entry: ResolvedContextEntry,
    references: Sequence[GoogleSearchConsoleUrlReference],
) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for reference in references:
        current = await get_sitemap(
            client,
            site_url=entry.external_id,
            sitemap_url=reference.url,
        )
        prepared.append(
            {
                "sitemap_url": reference.url,
                "previously_submitted": current is not None,
            }
        )
    return prepared


def _submitted_outcome(
    item: Mapping[str, Any],
    status: Mapping[str, Any] | None,
) -> dict[str, Any]:
    status_read = status is not None
    return {
        **item,
        "outcome": "submitted",
        "last_submitted": status.get("last_submitted") if status else None,
        "is_pending": status.get("is_pending") if status else None,
        "warnings": status.get("warnings") if status else None,
        "errors": status.get("errors") if status else None,
        "status_read": status_read,
        "error_code": None if status_read else "status_unavailable",
        "message": (
            None
            if status_read
            else "The sitemap was submitted, but Google did not return its status. Check it in Search Console."
        ),
    }


def _failed_outcome(item: Mapping[str, Any], exc: IntegrationError) -> dict[str, Any]:
    ambiguous = exc.failure_disposition is IntegrationFailureDisposition.AMBIGUOUS
    return {
        **item,
        "outcome": "unverified" if ambiguous else "failed",
        "last_submitted": None,
        "is_pending": None,
        "warnings": None,
        "errors": None,
        "status_read": False,
        "error_code": "unverified" if ambiguous else "rejected",
        "message": (
            "Google may or may not have received the submission. Check the sitemap in Search Console before submitting again."
            if ambiguous
            else "Google rejected the sitemap submission. Check the sitemap and your property access in Search Console."
        ),
    }


def _cancelled_outcome(
    item: Mapping[str, Any],
    *,
    ambiguous: bool,
) -> dict[str, Any]:
    return {
        **item,
        "outcome": "unverified" if ambiguous else "failed",
        "last_submitted": None,
        "is_pending": None,
        "warnings": None,
        "errors": None,
        "status_read": False,
        "error_code": "unverified" if ambiguous else "rejected",
        "message": (
            "Google may or may not have received the submission. Check the sitemap in Search Console before submitting again."
            if ambiguous
            else "The sitemap was not submitted because the action stopped before it was sent."
        ),
    }


def _attach_cancellation_evidence(
    exc: asyncio.CancelledError,
    pending: PendingIntegrationOperationDetail,
    prepared: Sequence[Mapping[str, Any]],
    completed: list[dict[str, Any]],
    current: Mapping[str, Any] | None,
) -> None:
    _attach_interruption_evidence(
        exc,
        pending,
        prepared,
        completed,
        current,
        default_disposition=(
            IntegrationFailureDisposition.AMBIGUOUS
            if current is not None
            else IntegrationFailureDisposition.NOT_DISPATCHED
        ),
    )


def _attach_interruption_evidence(
    exc: BaseException,
    pending: PendingIntegrationOperationDetail,
    prepared: Sequence[Mapping[str, Any]],
    completed: list[dict[str, Any]],
    current: Mapping[str, Any] | None,
    *,
    default_disposition: IntegrationFailureDisposition,
) -> None:
    disposition = getattr(exc, "failure_disposition", default_disposition)
    remaining_index = len(completed)
    remaining = prepared[remaining_index:]
    for index, item in enumerate(remaining):
        completed.append(
            _cancelled_outcome(
                item,
                ambiguous=index == 0 and disposition is IntegrationFailureDisposition.AMBIGUOUS,
            )
        )
    exc.failure_disposition = disposition
    exc.operation_detail = sitemap_terminal_detail(pending, completed)


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    sitemap_urls = args.get("sitemap_urls")
    if not isinstance(sitemap_urls, list) or not all(
        isinstance(item, str) for item in sitemap_urls
    ):
        raise TypeError("Search Console sitemap approval arguments are invalid")
    active_context = deps.active_context
    entries = (
        tuple(
            entry
            for entry in active_context.compatible_entries(GOOGLE_SEARCH_CONSOLE_WRITE_BINDING)
            if entry.write_allowed
        )
        if active_context is not None
        else ()
    )
    references = sitemap_references_for_entries(entries, sitemap_urls)
    entries_by_scope = {entry.external_id: entry for entry in entries}
    status_items: list[dict[str, Any]] = []
    clients: dict[str, GoogleSearchConsoleClient] = {}
    for reference in references:
        entry = entries_by_scope[reference.site_url]
        client = clients.get(reference.site_url)
        if client is None:
            client = await google_search_console_client_for_principal(
                deps.db,
                actor=deps.user,
                workspace=deps.workspace,
                entry=entry,
            )
            clients[reference.site_url] = client
        current = await get_sitemap(
            client,
            site_url=entry.external_id,
            sitemap_url=reference.url,
        )
        status_items.append(
            {
                "sitemap_url": reference.url,
                "site_url": reference.site_url,
                "previously_submitted": current is not None,
            }
        )
    writable_sites = list(dict.fromkeys(entry.external_id for entry in entries))
    return {
        **args,
        "_sitemap_submission_status": status_items,
        "_sitemap_writable_sites": writable_sites,
    }


DEFINITION = RuntimeToolDefinition(
    name="google_search_console_submit_sitemap",
    function=google_search_console_submit_sitemap,
    description=(
        "Submit or resubmit up to 20 sitemaps from selected writable Google Search Console "
        "properties. This asks Google to re-process the URLs listed in each sitemap; Google "
        "decides when and whether to crawl them."
    ),
    provider="google_search_console",
    label="Submit Search Console Sitemaps",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=True,
    takes_ctx=True,
    timeout=60,
    output_model=GoogleSearchConsoleSubmitSitemapsOutput,
    max_result_chars=MAX_SITEMAP_RESULT_CHARS,
    max_public_result_chars=MAX_SITEMAP_PUBLIC_RESULT_CHARS,
    integration_binding=GOOGLE_SEARCH_CONSOLE_WRITE_BINDING,
    approval_display_args=_approval_display_args,
    presentation=ToolPresentation(
        icon="google_search_console",
        running_label="Submitting Search Console Sitemaps",
        completed_label="Submitted Search Console Sitemaps",
        failed_label="Couldn't Submit Search Console Sitemaps",
        approval_title="Submit Sitemaps to Google Search Console",
        approval_prompt=(
            "The agent wants Google to re-process these sitemaps. Google decides when and "
            "whether to crawl the URLs they list."
        ),
        approve_label="Approve & Submit",
        arg_fields=(
            ToolFieldPresentation(
                key="sitemap_urls",
                label="Sitemap URLs",
                format="list",
                editable=True,
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
