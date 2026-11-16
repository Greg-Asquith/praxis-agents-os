# apps/api/integrations/outlook_calendar/tools/utils.py

"""Outlook Calendar context binding, credentials, write evidence, and bounded results."""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, ValidationError
from pydantic_ai import ModelRetry
from pydantic_core import to_json

from core.exceptions.integration import IntegrationFailureDisposition
from services.agents.runtime.tools.contract import IntegrationToolBinding, ToolFieldPresentation
from services.audit_events import (
    AuditStatus,
    IntegrationOperationCounts,
    IntegrationOperationEffect,
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    IntegrationOperationOutcome,
    IntegrationOperationOutcomeGroup,
    IntegrationOperationTarget,
    PendingIntegrationOperationDetail,
    TerminalIntegrationOperationDetail,
    terminal_applied_operation_detail,
)
from services.integrations.approved_display_args import approved_display_args
from services.integrations.connections.utils import refresh_oauth_credential
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.context.schemas import MAX_ACTIVE_CONTEXT_TARGETS
from services.integrations.context.targeted import run_context_scope
from services.integrations.credentials import (
    ensure_fresh_credential,
    get_usable_connection_credential,
)
from services.integrations.microsoft_graph import MicrosoftGraphClient
from services.integrations.operations import IntegrationAuditOutcome
from services.integrations.utils import integration_failure_code
from services.integrations.write_lifecycle import IntegrationWriteCallbacks

from ..operations.utils import CalendarWriteState, effective_time_zone, untrusted
from ..references import OutlookCalendarReference, OutlookEventReference
from ..settings import outlook_calendar_settings

OUTLOOK_CALENDAR_BINDING = IntegrationToolBinding(
    provider_keys=frozenset({"outlook_calendar"}), resource_types=frozenset({"outlook_calendar"})
)
OUTLOOK_CALENDAR_WRITE_BINDING = IntegrationToolBinding(
    provider_keys=OUTLOOK_CALENDAR_BINDING.provider_keys,
    resource_types=OUTLOOK_CALENDAR_BINDING.resource_types,
    requires_write=True,
)
RESULTS_FIELD = (ToolFieldPresentation(key="results", label="Calendars", format="list"),)
TIME_ZONE_FIELD = ToolFieldPresentation(
    key="time_zone", label="Time Zone", format="text", editable=True, secondary=True
)
MAX_RESULT_BYTES = 768 * 1024
LocalDateTime = Annotated[
    str,
    Field(
        min_length=10,
        max_length=32,
        description="Local date and time without a UTC offset, such as 2026-11-16T09:00:00.",
    ),
]
TimeZone = Annotated[
    str | None,
    Field(
        max_length=64,
        description="IANA time zone, such as Europe/London. Defaults to the mailbox time zone.",
    ),
]


def bounded_output(results) -> dict:
    output = {"results": serialize_fan_out_results(results)}
    if len(to_json(output)) > MAX_RESULT_BYTES:
        raise ModelRetry(
            "Outlook returned too much data. Select fewer calendars or ask for fewer results."
        )
    return output


async def calendar_client(ctx, entry) -> MicrosoftGraphClient:
    return await calendar_client_for_principal(
        ctx.deps.db, actor=ctx.deps.user, workspace=ctx.deps.workspace, entry=entry
    )


async def calendar_client_for_principal(db, *, actor, workspace, entry) -> MicrosoftGraphClient:
    async def access_token(force: bool) -> str:
        usable = await get_usable_connection_credential(
            db, connection_id=entry.connection_id, actor=actor, workspace=workspace
        )
        credential = await ensure_fresh_credential(
            db, credential_id=usable.id, refresh_token=refresh_oauth_credential, force=force
        )
        if not credential.access_token:
            raise ModelRetry("The Outlook Calendar connection needs to be reconnected.")
        return credential.access_token

    return MicrosoftGraphClient(
        access_token, provider_key="outlook_calendar", pacing_key=str(entry.connection_id)
    )


def outlook_calendar_available() -> bool:
    return bool(outlook_calendar_settings.OUTLOOK_CALENDAR_OAUTH_CLIENT_ID.strip())


def can_view_private(entry) -> bool:
    return entry.permissions_metadata.get("can_view_private_items") is True


def entry_time_zone(entry, requested: str | None) -> str:
    return effective_time_zone(requested, entry.permissions_metadata)


def model_input[T](parse: Callable[[], T]) -> T:
    """Returns the parsed input, turning a validation message into a model retry."""
    try:
        return parse()
    except ValueError as exc:
        raise ModelRetry(str(exc)) from None


def event_result(entry, event: dict) -> dict:
    # A fixed label keeps provider text out of the unframed reference.
    return {key: value for key, value in event.items() if key != "event_id"} | {
        "reference": OutlookEventReference(
            calendar_id=entry.external_id, event_id=event["event_id"], label="Outlook event"
        )
    }


async def run_once_per_connection(ctx, operation: Callable[[Any], Awaitable[Any]]) -> list:
    """Runs a mailbox-level query once per connection, using its first selected calendar."""
    active = ctx.deps.active_context
    entries = (
        active.compatible_entries(OUTLOOK_CALENDAR_BINDING)[:MAX_ACTIVE_CONTEXT_TARGETS]
        if active
        else ()
    )
    if not entries:
        raise ModelRetry(
            "No compatible resources in the active context. "
            "Ask the user to select a context that includes Outlook Calendar."
        )
    first_entries: dict = {}
    for entry in entries:
        first_entries.setdefault(entry.connection_id, entry)
    results = []
    for entry in first_entries.values():
        results.extend(
            await run_context_scope(
                ctx,
                binding=OUTLOOK_CALENDAR_BINDING,
                provider_scope_id=entry.external_id,
                operation=operation,
            )
        )
    return results


def calendar_reference(entry) -> OutlookCalendarReference:
    # The calendar name is the operator's own label for a resource they selected.
    return OutlookCalendarReference(
        calendar_id=entry.external_id,
        label=entry.display_name[:500] or "Outlook calendar",
        scope_label=entry.connection_label[:500] if entry.connection_label else None,
    )


def _writable_entries(deps) -> tuple:
    active = deps.active_context
    entries = active.compatible_entries(OUTLOOK_CALENDAR_BINDING) if active else ()
    return tuple(entry for entry in entries if entry.write_allowed)


def select_calendar_entry(deps, calendar: OutlookCalendarReference | None):
    """Returns the one writable calendar a new event goes in."""
    entries = _writable_entries(deps)
    if calendar is not None:
        entry = next((item for item in entries if item.external_id == calendar.calendar_id), None)
        if entry is None:
            raise ModelRetry("The calendar must be a selected Outlook calendar you can edit.")
        return entry
    defaults = [entry for entry in entries if entry.permissions_metadata.get("is_default") is True]
    if len(entries) == 1 or len(defaults) == 1:
        return entries[0] if len(entries) == 1 else defaults[0]
    if not entries:
        raise ModelRetry("Select an Outlook calendar you can edit before creating an event.")
    names = ", ".join(entry.display_name for entry in entries)
    raise ModelRetry(f"Choose the calendar for this event. Selected calendars: {names}.")


def event_calendar_entry(deps, event: OutlookEventReference):
    """Returns the writable selected calendar that holds the event."""
    entry = next(
        (item for item in _writable_entries(deps) if item.external_id == event.calendar_id), None
    )
    if entry is None:
        raise ModelRetry("The event must belong to a selected Outlook calendar you can edit.")
    return entry


def transaction_id(ctx) -> str:
    """Returns the same ID each time one approved call runs, so Graph drops a repeat create."""
    return str(
        uuid5(NAMESPACE_URL, f"praxis:outlook_calendar:{ctx.deps.run.id}:{ctx.tool_call_id}")
    )


def pending_write_detail(entry, *, action: str, fields: dict, event_id: str | None = None):
    return PendingIntegrationOperationDetail(
        target=IntegrationOperationTarget(
            entity_type="outlook_calendar",
            external_id=entry.external_id,
            display_name=entry.display_name,
            integration_resource_id=str(entry.integration_resource_id),
        ),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key=f"event:{action}",
                action=action,
                entity_type="outlook_event",
                external_id=event_id,
                items=[IntegrationOperationIntent(fields=fields)],
            )
        ],
    )


class CalendarWriteCallbacks(IntegrationWriteCallbacks):
    def __init__(self, entry, state, prepare_operation):
        super().__init__(
            prepare_operation=prepare_operation,
            successful=lambda pending: _successful_outcome(entry, pending, state),
            failed=lambda pending, exc: _failed_outcome(entry, pending, state, exc),
            cancelled=lambda exc, pending: _attach_cancellation(exc, pending, state),
        )


def write_result(entry, state: CalendarWriteState, *, outcome: str, error_code=None, detail=None):
    event_id = state.event_id
    return {
        "event": (
            OutlookEventReference(
                calendar_id=entry.external_id, event_id=event_id, label="Outlook event"
            )
            if event_id
            else None
        ),
        "action": state.action,
        "event_type": state.event_type,
        "web_link": untrusted(event_id, state.web_link) if event_id and state.web_link else None,
        "join_url": untrusted(event_id, state.join_url) if event_id and state.join_url else None,
        "outcome": outcome,
        "error_code": error_code,
        "detail": detail,
    }


def _successful_outcome(entry, pending, state: CalendarWriteState):
    return IntegrationAuditOutcome(
        write_result(entry, state, outcome="applied"),
        external_ref=state.event_id,
        operation_detail=terminal_applied_operation_detail(pending, external_ref=state.event_id),
    )


def _failed_detail(pending, state: CalendarWriteState, *, ambiguous: bool, error_code: str):
    status = "unverified" if ambiguous else "failed"
    counts = {
        "applied": 0,
        "skipped": 0,
        "failed": int(not ambiguous),
        "unverified": int(ambiguous),
    }
    return TerminalIntegrationOperationDetail(
        target=pending.target,
        intent_groups=pending.intent_groups,
        outcome_groups=[
            IntegrationOperationOutcomeGroup(
                key=pending.intent_groups[0].key,
                outcomes=[
                    IntegrationOperationOutcome(
                        intent_index=0,
                        status=status,
                        effects=[
                            IntegrationOperationEffect(
                                status=status,
                                error_code=error_code,
                                fields={"action": state.action},
                            )
                        ],
                    )
                ],
            )
        ],
        intent_counts=IntegrationOperationCounts(**counts),
        effect_counts=IntegrationOperationCounts(**counts),
    )


_FAILURE_DETAIL = {
    "not_organizer": (
        "Only the organiser can cancel this meeting. Use outlook_calendar_respond_to_event "
        "to decline it instead."
    ),
    "occurrence_boundary": (
        "An occurrence cannot move past the next or previous occurrence in its series."
    ),
}


def _failed_outcome(entry, pending, state: CalendarWriteState, exc):
    ambiguous = getattr(exc, "failure_disposition", None) in {
        None,
        IntegrationFailureDisposition.AMBIGUOUS,
    }
    error_code = "unverified_mutation" if ambiguous else integration_failure_code(exc)
    detail = (
        "Outlook could not confirm the change. Check the calendar before trying again."
        if ambiguous
        else _FAILURE_DETAIL.get(error_code)
    )
    result = write_result(
        entry,
        state,
        outcome="unverified" if ambiguous else "failed",
        error_code=error_code,
        detail=detail,
    )
    return IntegrationAuditOutcome(
        result,
        status=AuditStatus.UNVERIFIED if ambiguous else AuditStatus.FAILURE,
        external_ref=state.event_id,
        operation_detail=_failed_detail(pending, state, ambiguous=ambiguous, error_code=error_code),
        unverified_result=result if ambiguous else None,
    )


def _attach_cancellation(exc, pending, state: CalendarWriteState):
    disposition = getattr(exc, "failure_disposition", IntegrationFailureDisposition.AMBIGUOUS)
    exc.failure_disposition = disposition
    exc.operation_detail = _failed_detail(
        pending,
        state,
        ambiguous=disposition is IntegrationFailureDisposition.AMBIGUOUS,
        error_code="cancelled",
    )


def write_display_args(input_model, deps, args: dict) -> dict:
    """Shows the calendar and time zone a write uses when the agent left them out."""
    try:
        parsed = input_model.model_validate(args)
    except ValidationError:
        raise ValueError("Review the Outlook event fields and their required values.") from None
    values = parsed.model_dump(mode="json")
    if "calendar" in values:
        entry = select_calendar_entry(deps, parsed.calendar)
        values["calendar"] = calendar_reference(entry).model_dump(mode="json")
        values["attendees"] = values["attendees"] or []
        # The card hides the calendar picker when there is nothing else to pick.
        values["_calendar_choice"] = len(_writable_entries(deps)) > 1
    elif "event" in values:
        entry = event_calendar_entry(deps, parsed.event)
    else:
        return values
    if "time_zone" in values:
        values["time_zone"] = entry_time_zone(entry, parsed.time_zone)
    return values


def approved_default(ctx, key: str, value):
    """Returns the value, else the default the approver saw for it."""
    return value if value is not None else approved_display_args(ctx).get(key)
