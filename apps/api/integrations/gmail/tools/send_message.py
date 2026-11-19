# apps/api/integrations/gmail/tools/send_message.py

"""Send Gmail message runtime tool."""

from typing import Annotated, Any

from pydantic import AfterValidator, Field
from pydantic_ai import ModelRetry, RunContext

from core.exceptions.general import AppValidationError
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
from services.audit_events import (
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    IntegrationOperationTarget,
    PendingIntegrationOperationDetail,
    terminal_applied_operation_detail,
)
from services.email_suppressions import flag_suppressed_recipients, refuse_suppressed_recipients
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.fan_out import run_context_fan_out
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)
from utils.validation import validate_bare_email

from ..operations.send_message import send_message
from .schemas import GmailSendOutput
from .utils import (
    GMAIL_WRITE_BINDING,
    RESULTS_FIELD,
    gmail_available,
    gmail_client,
)


def _plain_address(value: str) -> str:
    # A display name or a second address in one value would get past the Do Not Email check.
    value = value.strip()
    try:
        validate_bare_email(value)
    except AppValidationError:
        raise ValueError("Give each recipient as one email address, without a name.") from None
    return value


Recipient = Annotated[str, AfterValidator(_plain_address)]


async def gmail_send_message(
    ctx: RunContext[RuntimeDeps],
    to: Annotated[list[Recipient], Field(min_length=1, description="Recipient email addresses.")],
    subject: Annotated[str, Field(description="Email subject.")],
    body_html: Annotated[
        str,
        Field(
            description=(
                "HTML email body. Use simple, inline-styled HTML (paragraphs, headings, "
                "lists, tables, links). A plain-text alternative is derived automatically."
            )
        ),
    ],
    cc: Annotated[list[Recipient] | None, Field(description="Optional CC recipients.")] = None,
    bcc: Annotated[list[Recipient] | None, Field(description="Optional BCC recipients.")] = None,
) -> dict[str, Any]:
    try:
        recipients, cc, bcc = (
            [_plain_address(value) for value in values or () if value.strip()]
            for values in (to, cc, bcc)
        )
    except ValueError as exc:
        raise ModelRetry(str(exc)) from None
    if not recipients:
        raise ModelRetry("gmail_send_message requires at least one recipient.")

    async def operation(entry: ResolvedContextEntry) -> Any:
        pending_detail = _pending_operation_detail(
            entry,
            recipient_count=len(recipients),
            cc_count=len(cc),
            bcc_count=len(bcc),
        )

        async def execute() -> Any:
            await refuse_suppressed_recipients(
                ctx.deps.db,
                workspace_id=ctx.deps.workspace.id,
                addresses=[*recipients, *cc, *bcc],
                provider_key="gmail",
                operation="send_message",
            )
            client = await gmail_client(ctx, entry)
            result = await send_message(
                client,
                to=recipients,
                subject=subject,
                body_html=body_html,
                cc=cc,
                bcc=bcc,
            )
            external_ref = str(result.get("message_id", "")) or None
            return IntegrationAuditOutcome(
                result,
                external_ref=external_ref,
                operation_detail=terminal_applied_operation_detail(
                    pending_detail,
                    external_ref=external_ref,
                ),
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="gmail_send_message",
            operation="send_message",
            execute=execute,
            pending_operation_detail=pending_detail,
        )

    results = await run_context_fan_out(
        ctx,
        binding=GMAIL_WRITE_BINDING,
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


async def _display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    return await flag_suppressed_recipients(
        deps.db, workspace_id=deps.workspace.id, display_args=args
    )


def _pending_operation_detail(
    entry: ResolvedContextEntry,
    *,
    recipient_count: int,
    cc_count: int,
    bcc_count: int,
) -> PendingIntegrationOperationDetail:
    return PendingIntegrationOperationDetail(
        target=IntegrationOperationTarget(
            entity_type="gmail_mailbox",
            external_id=entry.external_id,
            display_name=entry.display_name,
            integration_resource_id=str(entry.integration_resource_id),
        ),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key="message:send",
                action="send",
                entity_type="gmail_message",
                items=[
                    IntegrationOperationIntent(
                        fields={
                            "recipient_count": recipient_count,
                            "cc_count": cc_count,
                            "bcc_count": bcc_count,
                        }
                    )
                ],
            )
        ],
    )


DEFINITION = RuntimeToolDefinition(
    name="gmail_send_message",
    function=gmail_send_message,
    description=(
        "Send a rich HTML email from every writable Gmail mailbox in context. "
        "A plain-text alternative is derived from the HTML automatically."
    ),
    provider="gmail",
    label="Send Gmail Message",
    code_eligible=False,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=60,
    output_model=GmailSendOutput,
    integration_binding=GMAIL_WRITE_BINDING,
    availability_check=gmail_available,
    approval_display_args=_display_args,
    presentation=ToolPresentation(
        icon="gmail",
        running_label="Sending Gmail Message",
        completed_label="Sent Gmail Message",
        failed_label="Couldn't Send Gmail Message",
        approval_title="Send Gmail Message",
        approval_prompt="The agent wants to send this email from the selected mailbox.",
        approve_label="Approve & Send",
        arg_fields=(
            ToolFieldPresentation(key="to", label="To", format="list", editable=True),
            ToolFieldPresentation(key="subject", label="Subject", editable=True),
            ToolFieldPresentation(
                key="body_html",
                label="Message",
                format="html",
                editable=True,
            ),
            ToolFieldPresentation(
                key="cc",
                label="Cc",
                format="list",
                editable=True,
                secondary=True,
            ),
            ToolFieldPresentation(
                key="bcc",
                label="Bcc",
                format="list",
                editable=True,
                secondary=True,
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
