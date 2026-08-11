# apps/api/integrations/gmail/tools/send_message.py

"""Send Gmail message runtime tool."""

from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

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
    IntegrationOperationChange,
    IntegrationOperationCounts,
    IntegrationOperationDetail,
    IntegrationOperationTarget,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.fan_out import run_context_fan_out
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.send_message import send_message
from .schemas import GmailSendOutput
from .utils import (
    GMAIL_WRITE_BINDING,
    RESULTS_FIELD,
    gmail_available,
    gmail_client,
)


async def gmail_send_message(
    ctx: RunContext[RuntimeDeps],
    to: Annotated[list[str], Field(min_length=1, description="Recipient email addresses.")],
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
    cc: Annotated[list[str] | None, Field(description="Optional CC recipients.")] = None,
    bcc: Annotated[list[str] | None, Field(description="Optional BCC recipients.")] = None,
) -> dict[str, Any]:
    recipients = [value.strip() for value in to if value.strip()]
    if not recipients:
        raise ModelRetry("gmail_send_message requires at least one recipient.")

    async def operation(entry: ResolvedContextEntry) -> Any:
        async def execute() -> Any:
            client = await gmail_client(ctx, entry)
            result = await send_message(
                client,
                to=recipients,
                subject=subject,
                body_html=body_html,
                cc=cc,
                bcc=bcc,
            )
            return IntegrationAuditOutcome(
                result,
                external_ref=str(result.get("message_id", "")) or None,
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="gmail_send_message",
            operation="send_message",
            execute=execute,
            pending_operation_detail=_pending_operation_detail(
                entry,
                recipient_count=len(recipients),
                cc_count=len(cc or ()),
                bcc_count=len(bcc or ()),
            ),
        )

    results = await run_context_fan_out(
        ctx,
        binding=GMAIL_WRITE_BINDING,
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


def _pending_operation_detail(
    entry: ResolvedContextEntry,
    *,
    recipient_count: int,
    cc_count: int,
    bcc_count: int,
) -> IntegrationOperationDetail:
    return IntegrationOperationDetail(
        target=IntegrationOperationTarget(
            entity_type="gmail_mailbox",
            external_id=entry.external_id,
            display_name=entry.display_name,
            integration_resource_id=str(entry.integration_resource_id),
        ),
        changes=[
            IntegrationOperationChange(
                action="send",
                entity_type="gmail_message",
                fields={
                    "recipient_count": recipient_count,
                    "cc_count": cc_count,
                    "bcc_count": bcc_count,
                },
            )
        ],
        counts=IntegrationOperationCounts(applied=0, skipped=0, failed=0),
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
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    takes_ctx=True,
    timeout=60,
    output_model=GmailSendOutput,
    integration_binding=GMAIL_WRITE_BINDING,
    availability_check=gmail_available,
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
