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
from services.audit_events import AuditStatus
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.fan_out import run_context_fan_out

from ..operations.send_message import send_message
from .schemas import GmailSendOutput
from .utils import (
    GMAIL_WRITE_BINDING,
    RESULTS_FIELD,
    fan_out_dict,
    gmail_available,
    gmail_client,
    record_gmail_operation_audit,
    run_audited_operation,
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
            return await send_message(
                client,
                to=recipients,
                subject=subject,
                body_html=body_html,
                cc=cc,
                bcc=bcc,
            )

        return await run_audited_operation(
            ctx,
            entry,
            tool_name="gmail_send_message",
            operation="send_message",
            execute=execute,
            external_ref_from_result=lambda value: str(value.get("message_id", "")) or None,
        )

    async def audit_write_denied(entry: ResolvedContextEntry) -> None:
        await record_gmail_operation_audit(
            ctx,
            entry,
            tool_name="gmail_send_message",
            operation="send_message",
            status=AuditStatus.FAILURE,
            error_code="write_not_permitted",
        )

    results = await run_context_fan_out(
        ctx.deps,
        binding=GMAIL_WRITE_BINDING,
        operation=operation,
        write=True,
        on_write_denied=audit_write_denied,
    )
    return {"results": [fan_out_dict(item) for item in results]}


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
