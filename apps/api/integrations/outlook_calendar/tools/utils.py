# apps/api/integrations/outlook_calendar/tools/utils.py

"""Outlook Calendar context binding, credentials, and bounded result helpers."""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry
from pydantic_core import to_json

from services.agents.runtime.tools.contract import IntegrationToolBinding, ToolFieldPresentation
from services.integrations.connections.utils import refresh_oauth_credential
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.context.schemas import MAX_ACTIVE_CONTEXT_TARGETS
from services.integrations.context.targeted import run_context_scope
from services.integrations.credentials import (
    ensure_fresh_credential,
    get_usable_connection_credential,
)
from services.integrations.microsoft_graph import MicrosoftGraphClient

from ..operations.utils import effective_time_zone
from ..references import OutlookEventReference
from ..settings import outlook_calendar_settings

OUTLOOK_CALENDAR_BINDING = IntegrationToolBinding(
    provider_keys=frozenset({"outlook_calendar"}), resource_types=frozenset({"outlook_calendar"})
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
