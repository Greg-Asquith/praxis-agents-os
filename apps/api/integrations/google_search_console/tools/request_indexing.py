# apps/api/integrations/google_search_console/tools/request_indexing.py

"""Send approval-only notifications through Google's restricted Indexing API."""

import asyncio
from collections.abc import Mapping, Sequence
from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext, ToolReturn

from core.exceptions.integration import (
    IntegrationError,
    IntegrationFailureDisposition,
    IntegrationPermissionError,
    IntegrationRateLimitError,
)
from integrations.google_search_console.references import GoogleSearchConsoleUrlReference
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_EXTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_EXTERNAL_WRITE,
    TOOL_POLICY_APPROVAL,
    RuntimeToolDefinition,
    ToolFieldColumn,
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

from ..operations.get_url_notification_metadata import get_url_notification_metadata
from ..operations.publish_url_notification import publish_url_notification
from .schemas import (
    GoogleSearchConsoleIndexingNotification,
    GoogleSearchConsoleRequestIndexingOutput,
)
from .utils import indexing_notification_results
from .utils.bindings import GOOGLE_SEARCH_CONSOLE_WRITE_BINDING, RESULTS_FIELD
from .utils.client import (
    google_search_console_client,
    google_search_console_indexing_available,
)
from .utils.mutation_evidence import audit_status, indexing_pending_detail, indexing_terminal_detail
from .utils.routing import indexing_references_for_entries

MAX_NOTIFICATIONS_PER_REQUEST = 20
MAX_INDEXING_RESULT_CHARS = 120_000
MAX_INDEXING_PUBLIC_RESULT_CHARS = 160_000
_ERROR_MESSAGES = {
    "api_not_enabled": "Enable the Indexing API in the Google Cloud project, then try again.",
    "not_owner": "Grant the connected account Owner permission for this Search Console property.",
    "quota_exhausted": (
        "The Google Cloud project has reached the Indexing API limit of 200 notifications per day."
    ),
    "rejected": "Google rejected the notification. Check the URL and its eligible page type.",
    "scope_missing": "Reconnect Google Search Console to grant the Indexing API permission.",
    "unverified": (
        "Google may or may not have received the notification. Check Search Console before trying "
        "again."
    ),
}


async def google_search_console_request_indexing(
    ctx: RunContext[RuntimeDeps],
    notifications: Annotated[
        list[GoogleSearchConsoleIndexingNotification],
        Field(
            min_length=1,
            max_length=MAX_NOTIFICATIONS_PER_REQUEST,
            description=(
                "Eligible job posting or livestream video URL notifications, with no "
                "duplicate URLs."
            ),
        ),
    ],
) -> ToolReturn[dict[str, Any]]:
    active_context = ctx.deps.active_context
    entries = (
        active_context.compatible_entries(GOOGLE_SEARCH_CONSOLE_WRITE_BINDING)
        if active_context is not None
        else ()
    )
    items_by_url = _notifications_by_url(notifications)
    references = indexing_references_for_entries(entries, list(items_by_url))
    _require_owner(entries, references)

    async def operation(
        entry: ResolvedContextEntry,
        scoped_references: Sequence[GoogleSearchConsoleUrlReference],
    ) -> Any:
        prepared = [items_by_url[reference.url] for reference in scoped_references]
        pending = indexing_pending_detail(entry, prepared)

        async def execute() -> IntegrationAuditOutcome[dict[str, dict[str, Any]]]:
            client = await google_search_console_client(ctx, entry)
            outcomes: list[dict[str, Any]] = []
            for item in prepared:
                try:
                    await publish_url_notification(
                        client,
                        url=str(item["url"]),
                        notification_type=item["notification_type"],
                    )
                except asyncio.CancelledError as exc:
                    _attach_interruption_evidence(
                        exc,
                        pending,
                        prepared,
                        outcomes,
                        current=item,
                        disposition=IntegrationFailureDisposition.AMBIGUOUS,
                    )
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
                        current=item,
                        disposition=IntegrationFailureDisposition.AMBIGUOUS,
                    )
                    raise

                try:
                    metadata = await get_url_notification_metadata(
                        client,
                        url=str(item["url"]),
                        notification_type=item["notification_type"],
                    )
                except asyncio.CancelledError as exc:
                    outcomes.append(_notified_outcome(item, None))
                    _attach_interruption_evidence(
                        exc,
                        pending,
                        prepared,
                        outcomes,
                        current=None,
                        disposition=IntegrationFailureDisposition.NOT_DISPATCHED,
                    )
                    raise
                except IntegrationError:
                    metadata = None
                except Exception as exc:
                    outcomes.append(_notified_outcome(item, None))
                    _attach_interruption_evidence(
                        exc,
                        pending,
                        prepared,
                        outcomes,
                        current=None,
                        disposition=IntegrationFailureDisposition.REJECTED,
                    )
                    raise
                outcomes.append(_notified_outcome(item, metadata))

            terminal = indexing_terminal_detail(pending, outcomes)
            status = audit_status(terminal)
            result = indexing_notification_results(outcomes)
            return IntegrationAuditOutcome(
                result,
                status=status,
                external_ref=",".join(str(item["url"]) for item in prepared),
                operation_detail=terminal,
                unverified_result=result if status is AuditStatus.UNVERIFIED else None,
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_search_console_request_indexing",
            operation="request_indexing",
            execute=execute,
            pending_operation_detail=pending,
        )

    results = await run_context_targets(
        ctx,
        binding=GOOGLE_SEARCH_CONSOLE_WRITE_BINDING,
        references=references,
        operation=operation,
    )
    return split_fan_out_tool_return(results)


def _notifications_by_url(
    notifications: Sequence[GoogleSearchConsoleIndexingNotification],
) -> dict[str, dict[str, str]]:
    items: dict[str, dict[str, str]] = {}
    for notification in notifications:
        url = notification.url.strip()
        if url in items:
            raise ModelRetry(f"The URL {url!r} was provided more than once.")
        items[url] = {
            "url": url,
            "notification_type": notification.notification_type,
            "page_type": notification.page_type,
        }
    return items


def _require_owner(
    entries: Sequence[ResolvedContextEntry],
    references: Sequence[GoogleSearchConsoleUrlReference],
) -> None:
    referenced_sites = {reference.site_url for reference in references}
    for entry in entries:
        if entry.external_id not in referenced_sites:
            continue
        if entry.permissions_metadata.get("permission_level") != "siteOwner":
            raise ModelRetry(
                f"{entry.display_name!r} requires Search Console Owner permission before "
                "it can send Indexing API notifications."
            )


def _notified_outcome(
    item: Mapping[str, Any],
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        **item,
        "outcome": "notified",
        "notify_time": metadata.get("notify_time") if metadata else None,
        "error_code": None if metadata else "status_unavailable",
        "message": (
            None
            if metadata
            else "Google accepted the notification, but its status could not be read."
        ),
    }


def _failed_outcome(item: Mapping[str, Any], exc: IntegrationError) -> dict[str, Any]:
    provider_error_code = _indexing_error_code(exc)
    ambiguous = (
        exc.failure_disposition is IntegrationFailureDisposition.AMBIGUOUS
        and provider_error_code != "quota_exhausted"
    )
    error_code = "unverified" if ambiguous else provider_error_code
    return {
        **item,
        "outcome": "unverified" if ambiguous else "failed",
        "notify_time": None,
        "error_code": error_code,
        "message": _ERROR_MESSAGES[error_code],
    }


def _indexing_error_code(exc: IntegrationError) -> str:
    if isinstance(exc, IntegrationRateLimitError):
        return "quota_exhausted"
    detail = exc.user_message.upper()
    if "SERVICE_DISABLED" in detail:
        return "api_not_enabled"
    if "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in detail:
        return "scope_missing"
    if isinstance(exc, IntegrationPermissionError):
        return "not_owner"
    return "rejected"


def _interrupted_outcome(item: Mapping[str, Any], *, ambiguous: bool) -> dict[str, Any]:
    error_code = "unverified" if ambiguous else "rejected"
    return {
        **item,
        "outcome": "unverified" if ambiguous else "failed",
        "notify_time": None,
        "error_code": error_code,
        "message": _ERROR_MESSAGES[error_code],
    }


def _attach_interruption_evidence(
    exc: BaseException,
    pending: PendingIntegrationOperationDetail,
    prepared: Sequence[Mapping[str, Any]],
    completed: list[dict[str, Any]],
    *,
    current: Mapping[str, Any] | None,
    disposition: IntegrationFailureDisposition,
) -> None:
    resolved_disposition = getattr(exc, "failure_disposition", disposition)
    remaining = prepared[len(completed) :]
    for index, item in enumerate(remaining):
        completed.append(
            _interrupted_outcome(
                item,
                ambiguous=(
                    current is not None
                    and index == 0
                    and resolved_disposition is IntegrationFailureDisposition.AMBIGUOUS
                ),
            )
        )
    exc.failure_disposition = resolved_disposition
    exc.operation_detail = indexing_terminal_detail(pending, completed)


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    raw_notifications = args.get("notifications")
    if not isinstance(raw_notifications, list):
        raise TypeError("Search Console indexing approval arguments are invalid")
    notifications = [
        GoogleSearchConsoleIndexingNotification.model_validate(item) for item in raw_notifications
    ]
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
    items_by_url = _notifications_by_url(notifications)
    references = indexing_references_for_entries(entries, list(items_by_url))
    _require_owner(entries, references)
    return {
        **args,
        "_indexing_writable_sites": list(dict.fromkeys(entry.external_id for entry in entries)),
    }


DEFINITION = RuntimeToolDefinition(
    name="google_search_console_request_indexing",
    function=google_search_console_request_indexing,
    description=(
        "Send up to 20 Indexing API notifications for job posting or livestream video pages "
        "on selected Search Console properties. Google decides when and whether to crawl or "
        "index each page."
    ),
    provider="google_search_console",
    label="Send Search Console Indexing Notifications",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=60,
    output_model=GoogleSearchConsoleRequestIndexingOutput,
    max_result_chars=MAX_INDEXING_RESULT_CHARS,
    max_public_result_chars=MAX_INDEXING_PUBLIC_RESULT_CHARS,
    integration_binding=GOOGLE_SEARCH_CONSOLE_WRITE_BINDING,
    availability_check=google_search_console_indexing_available,
    approval_display_args=_approval_display_args,
    presentation=ToolPresentation(
        icon="google_search_console",
        running_label="Sending Search Console Indexing Notifications",
        completed_label="Sent Search Console Indexing Notifications",
        failed_label="Couldn't Send Search Console Indexing Notifications",
        approval_title="Send Indexing API Notifications",
        approval_prompt=(
            "Google accepts these notifications only for job posting pages and livestream "
            "video pages. Notifications for other pages are ignored and may violate Google's "
            "guidelines. A URL_DELETED notification asks Google to remove the page from its "
            "index. Before approving one, confirm that the page returns 404 or 410, or includes "
            "a noindex directive. Google decides when and whether to crawl, index, or remove "
            "each page."
        ),
        approve_label="Approve & Notify",
        arg_fields=(
            ToolFieldPresentation(
                key="notifications",
                label="Notifications",
                format="records",
                editable=True,
                min_rows=1,
                columns=(
                    ToolFieldColumn(key="url", label="URL", required=True),
                    ToolFieldColumn(
                        key="notification_type",
                        label="Notification",
                        options=("URL_UPDATED", "URL_DELETED"),
                        required=True,
                    ),
                    ToolFieldColumn(
                        key="page_type",
                        label="Eligible Page Type",
                        options=("job_posting", "broadcast_event"),
                        required=True,
                    ),
                ),
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
