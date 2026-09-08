# apps/api/integrations/outlook_mail/tools/utils.py

"""Outlook context binding, credentials, and bounded result helpers."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from pydantic import ValidationError
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
from services.integrations.connections.utils import refresh_oauth_credential
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.credentials import (
    ensure_fresh_credential,
    get_usable_connection_credential,
)
from services.integrations.microsoft_graph import MicrosoftGraphClient
from services.integrations.operations import IntegrationAuditOutcome
from services.integrations.utils import integration_failure_code

from ..operations.utils import MailWriteState, untrusted
from ..references import OutlookMessageReference
from ..settings import outlook_mail_settings

OUTLOOK_MAIL_BINDING = IntegrationToolBinding(
    provider_keys=frozenset({"outlook_mail"}), resource_types=frozenset({"outlook_mailbox"})
)
OUTLOOK_MAIL_WRITE_BINDING = IntegrationToolBinding(
    provider_keys=OUTLOOK_MAIL_BINDING.provider_keys,
    resource_types=OUTLOOK_MAIL_BINDING.resource_types,
    requires_write=True,
)
RESULTS_FIELD = (ToolFieldPresentation(key="results", label="Mailboxes", format="list"),)
MAX_RESULT_BYTES = 768 * 1024


@dataclass(frozen=True)
class PreparedMailWrite:
    pending: PendingIntegrationOperationDetail
    mutate: Callable[[], Awaitable[None]]


@dataclass
class MailWriteCallbacks:
    """Supplies preparation and outcome callbacks to the shared audit runner."""

    entry: ResolvedContextEntry
    state: MailWriteState
    prepare_operation: Callable[[], Awaitable[PreparedMailWrite]]
    _prepared: PreparedMailWrite | None = field(default=None, init=False)

    async def prepare(self) -> PendingIntegrationOperationDetail:
        self._prepared = await self.prepare_operation()
        return self._prepared.pending

    async def execute(self) -> IntegrationAuditOutcome[dict]:
        prepared = self._prepared
        if prepared is None:
            raise RuntimeError("Outlook write preparation did not complete.")
        # The shared runner persists pending intent before invoking this callback.
        try:
            await prepared.mutate()
        except asyncio.CancelledError as exc:
            attach_write_cancellation(exc, prepared.pending, self.state)
            raise
        except Exception as exc:
            return failed_write_outcome(self.entry, prepared.pending, self.state, exc)
        return successful_write_outcome(self.entry, prepared.pending, self.state)


def bounded_output(results) -> dict:
    output = {"results": serialize_fan_out_results(results)}
    if len(to_json(output)) > MAX_RESULT_BYTES:
        raise ModelRetry("Outlook returned too much data. Select fewer mailboxes or fewer results.")
    return output


async def mailbox_client(ctx, entry) -> MicrosoftGraphClient:
    return await mailbox_client_for_principal(
        ctx.deps.db, actor=ctx.deps.user, workspace=ctx.deps.workspace, entry=entry
    )


async def mailbox_client_for_principal(db, *, actor, workspace, entry) -> MicrosoftGraphClient:
    async def access_token(force: bool) -> str:
        usable = await get_usable_connection_credential(
            db, connection_id=entry.connection_id, actor=actor, workspace=workspace
        )
        credential = await ensure_fresh_credential(
            db, credential_id=usable.id, refresh_token=refresh_oauth_credential, force=force
        )
        if not credential.access_token:
            raise ModelRetry("The Outlook connection needs to be reconnected.")
        return credential.access_token

    return MicrosoftGraphClient(
        access_token, provider_key="outlook_mail", pacing_key=str(entry.connection_id)
    )


def outlook_mail_available() -> bool:
    return bool(outlook_mail_settings.OUTLOOK_MAIL_OAUTH_CLIENT_ID.strip())


def mailbox_time_zone(entry) -> str | None:
    value = entry.permissions_metadata.get("time_zone")
    return value[:100] if isinstance(value, str) else None


def message_result(entry, message: dict) -> dict:
    message_id = message["message_id"]
    return {key: value for key, value in message.items() if key != "message_id"} | {
        "reference": OutlookMessageReference(
            mailbox_id=entry.external_id, message_id=message_id, label="Outlook message"
        )
    }


def single_mailbox_entry(deps, reference: OutlookMessageReference | None = None):
    active = deps.active_context
    entries = active.compatible_entries(OUTLOOK_MAIL_BINDING) if active else ()
    if len(entries) != 1:
        raise ModelRetry("Select exactly one Outlook mailbox before changing or sending email.")
    entry = entries[0]
    if reference is not None and reference.mailbox_id != entry.external_id:
        raise ModelRetry("The message must belong to the selected Outlook mailbox.")
    return entry


def pending_write_detail(entry, *, action: str, fields: dict, message_id: str | None = None):
    return PendingIntegrationOperationDetail(
        target=IntegrationOperationTarget(
            entity_type="outlook_mailbox",
            external_id=entry.external_id,
            display_name=entry.display_name,
            integration_resource_id=str(entry.integration_resource_id),
        ),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key=f"message:{action}",
                action=action,
                entity_type="outlook_message",
                external_id=message_id,
                items=[IntegrationOperationIntent(fields=fields)],
            )
        ],
    )


def write_result(entry, state: MailWriteState, *, outcome: str, error_code=None, detail=None):
    return {
        "message": (
            OutlookMessageReference(
                mailbox_id=entry.external_id,
                message_id=state.message_id,
                label="Outlook message",
            )
            if state.message_id
            else None
        ),
        "web_link": untrusted(state.message_id, state.web_link) if state.web_link else None,
        "outcome": outcome,
        "error_code": error_code,
        "detail": detail,
    }


def successful_write_outcome(entry, pending, state: MailWriteState):
    return IntegrationAuditOutcome(
        write_result(entry, state, outcome="applied"),
        external_ref=state.message_id,
        operation_detail=terminal_applied_operation_detail(pending, external_ref=state.message_id),
    )


def failed_write_detail(pending, state: MailWriteState, *, ambiguous: bool, error_code: str):
    status = "unverified" if ambiguous else "failed"
    effects = [
        IntegrationOperationEffect(
            status="applied", external_ref=state.message_id, fields={"action": step}
        )
        for step in state.applied_steps
    ]
    effects.append(
        IntegrationOperationEffect(
            status=status, error_code=error_code, fields={"action": state.step}
        )
    )
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
                    IntegrationOperationOutcome(intent_index=0, status=status, effects=effects)
                ],
            )
        ],
        intent_counts=IntegrationOperationCounts(**counts),
        effect_counts=IntegrationOperationCounts(**{**counts, "applied": len(state.applied_steps)}),
    )


def failed_write_outcome(entry, pending, state: MailWriteState, exc):
    ambiguous = getattr(exc, "failure_disposition", None) in {
        None,
        IntegrationFailureDisposition.AMBIGUOUS,
    }
    error_code = (
        "unverified_mutation"
        if ambiguous
        else "send_failed"
        if state.step == "send" and state.message_id
        else integration_failure_code(exc)
    )
    detail = None
    if state.message_id and ("draft" in state.applied_steps or state.step == "send"):
        detail = (
            "Outlook could not confirm the change. Check the message before trying again."
            if ambiguous
            else "The change failed. Check the message in Outlook before trying again."
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
        external_ref=state.message_id,
        operation_detail=failed_write_detail(
            pending, state, ambiguous=ambiguous, error_code=error_code
        ),
        unverified_result=result if ambiguous else None,
    )


def attach_write_cancellation(exc, pending, state: MailWriteState):
    disposition = getattr(exc, "failure_disposition", IntegrationFailureDisposition.AMBIGUOUS)
    exc.failure_disposition = disposition
    exc.operation_detail = failed_write_detail(
        pending,
        state,
        ambiguous=disposition is IntegrationFailureDisposition.AMBIGUOUS,
        error_code="cancelled",
    )


def mutation_display_args(input_model, _deps, args: dict) -> dict:
    """Shows executed defaults without adding them to the replay payload."""
    try:
        values = input_model.model_validate(args).model_dump(mode="json")
    except ValidationError:
        raise ValueError("Review the Outlook message fields and their required values.") from None
    for key in ("cc", "bcc"):
        if key in values and values[key] is None and values.get("reply_to") is None:
            values[key] = []
    if values.get("reply_to") is not None:
        values["_recipient_inheritance"] = [
            key for key in ("to", "cc", "bcc") if values[key] is None
        ]
    return values
