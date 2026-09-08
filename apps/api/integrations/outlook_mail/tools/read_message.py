# apps/api/integrations/outlook_mail/tools/read_message.py

"""Read message in Outlook."""

from typing import Annotated

from pydantic import Field
from pydantic_ai import RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_EGRESS_PROVIDER_QUERY,
    TOOL_POLICY_AUTO,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.integrations.context.targeted import run_context_targets
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.get_message import get_message
from ..references import OutlookAttachmentReference, OutlookMessageReference
from .schemas import MessageOutput
from .utils import (
    OUTLOOK_MAIL_BINDING,
    RESULTS_FIELD,
    bounded_output,
    mailbox_client,
    mailbox_time_zone,
    message_result,
    outlook_mail_available,
)


# The Field description keeps the `message` wrapper in the model-facing schema; pydantic-ai
# unwraps a lone model-typed parameter otherwise, and approvals need the wrapper key.
async def outlook_mail_read_message(
    ctx: RunContext[RuntimeDeps],
    message: Annotated[
        OutlookMessageReference,
        Field(description="Scoped Outlook message reference returned by search."),
    ],
) -> dict:
    async def operation(entry, references):
        reference = references[0]

        async def execute():
            client = await mailbox_client(ctx, entry)
            result = await get_message(client, message_id=reference.message_id)
            result = message_result(entry, result)
            result["attachments"] = [
                {key: value for key, value in item.items() if key != "attachment_id"}
                | {
                    "reference": OutlookAttachmentReference(
                        mailbox_id=entry.external_id,
                        message_id=reference.message_id,
                        attachment_id=item["attachment_id"],
                        label="Outlook attachment",
                    )
                }
                for item in result["attachments"]
            ]
            return IntegrationAuditOutcome(
                {**result, "mailbox_time_zone": mailbox_time_zone(entry)},
                external_ref=reference.provider_entity_id,
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="outlook_mail_read_message",
            operation="read_message",
            execute=execute,
        )

    return bounded_output(
        await run_context_targets(
            ctx, binding=OUTLOOK_MAIL_BINDING, references=[message], operation=operation
        )
    )


DEFINITION = RuntimeToolDefinition(
    name="outlook_mail_read_message",
    function=outlook_mail_read_message,
    description=(
        "Reads an Outlook email using its message reference. Returns the message body, sender, "
        "recipients, and attachment details, with up to 50,000 body characters."
    ),
    provider="outlook_mail",
    label="Read message in Outlook",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    default_policy=TOOL_POLICY_AUTO,
    takes_ctx=True,
    timeout=60,
    output_model=MessageOutput,
    integration_binding=OUTLOOK_MAIL_BINDING,
    availability_check=outlook_mail_available,
    presentation=ToolPresentation(
        icon="outlook_mail",
        running_label="Reading Outlook message",
        completed_label="Read message in Outlook",
        failed_label="Could not read Outlook message",
        arg_fields=(
            ToolFieldPresentation(
                key="message", label="Message", format="entity", entity_kind="outlook_message"
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
