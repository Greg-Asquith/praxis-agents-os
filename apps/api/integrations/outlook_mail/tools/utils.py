# apps/api/integrations/outlook_mail/tools/utils.py

"""Outlook context binding, credentials, and bounded result helpers."""

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
from services.email_suppressions import (
    SUPPRESSED_RECIPIENT_ERROR_CODE,
    flag_suppressed_recipients,
    refuse_suppressed_recipients,
)
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.microsoft_graph import (
    MicrosoftGraphClient,
    graph_client_for_principal,
)
from services.integrations.operations import IntegrationAuditOutcome
from services.integrations.utils import integration_failure_code
from services.integrations.write_lifecycle import (
    IntegrationWriteCallbacks,
    PreparedIntegrationWrite,
)

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
PreparedMailWrite = PreparedIntegrationWrite


class MailWriteCallbacks(IntegrationWriteCallbacks):
    def __init__(self, entry, state, prepare_operation):
        super().__init__(
            prepare_operation=prepare_operation,
            successful=lambda pending: successful_write_outcome(entry, pending, state),
            failed=lambda pending, exc: failed_write_outcome(entry, pending, state, exc),
            cancelled=lambda exc, pending: attach_write_cancellation(exc, pending, state),
        )


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
    return graph_client_for_principal(
        db,
        actor=actor,
        workspace=workspace,
        entry=entry,
        provider_key="outlook_mail",
        reconnect_message="The Outlook connection needs to be reconnected.",
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
    if error_code == SUPPRESSED_RECIPIENT_ERROR_CODE:
        detail = exc.user_message
    elif state.message_id and ("draft" in state.applied_steps or state.step == "send"):
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


async def refuse_listed_recipients(ctx, state: MailWriteState, addresses, *, operation: str):
    """Refuses the send before Graph's send request when any recipient is on the Do Not Email list."""
    state.step = "check_recipients"
    await refuse_suppressed_recipients(
        ctx.deps.db,
        workspace_id=ctx.deps.workspace.id,
        addresses=addresses,
        provider_key="outlook_mail",
        operation=operation,
    )


async def recipient_display_args(input_model, deps, args: dict) -> dict:
    """Adds listed recipients to the mutation display so the card blocks approval."""
    return await flag_suppressed_recipients(
        deps.db,
        workspace_id=deps.workspace.id,
        display_args=mutation_display_args(input_model, deps, args),
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
