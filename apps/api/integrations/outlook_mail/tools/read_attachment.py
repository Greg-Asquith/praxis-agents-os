# apps/api/integrations/outlook_mail/tools/read_attachment.py

"""Read attachment in Outlook."""

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

from ..operations.get_attachment import get_attachment
from ..references import OutlookAttachmentReference
from .schemas import AttachmentOutput
from .utils import (
    OUTLOOK_MAIL_BINDING,
    RESULTS_FIELD,
    bounded_output,
    mailbox_client,
    mailbox_time_zone,
    outlook_mail_available,
)


# The Field description keeps the `attachment` wrapper in the model-facing schema; see read_message.
async def outlook_mail_read_attachment(
    ctx: RunContext[RuntimeDeps],
    attachment: Annotated[
        OutlookAttachmentReference,
        Field(description="Scoped Outlook attachment reference returned by reading a message."),
    ],
) -> dict:
    async def operation(entry, references):
        reference = references[0]

        async def execute():
            client = await mailbox_client(ctx, entry)
            result = await get_attachment(
                client, message_id=reference.message_id, attachment_id=reference.attachment_id
            )
            return IntegrationAuditOutcome(
                {**result, "mailbox_time_zone": mailbox_time_zone(entry)},
                external_ref=reference.provider_entity_id,
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="outlook_mail_read_attachment",
            operation="read_attachment",
            execute=execute,
        )

    return bounded_output(
        await run_context_targets(
            ctx, binding=OUTLOOK_MAIL_BINDING, references=[attachment], operation=operation
        )
    )


DEFINITION = RuntimeToolDefinition(
    name="outlook_mail_read_attachment",
    function=outlook_mail_read_attachment,
    description="Read attachment in Outlook as bounded text.",
    provider="outlook_mail",
    label="Read attachment in Outlook",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    default_policy=TOOL_POLICY_AUTO,
    takes_ctx=True,
    timeout=60,
    output_model=AttachmentOutput,
    integration_binding=OUTLOOK_MAIL_BINDING,
    availability_check=outlook_mail_available,
    presentation=ToolPresentation(
        icon="outlook_mail",
        running_label="Reading Outlook attachment",
        completed_label="Read attachment in Outlook",
        failed_label="Could not read Outlook attachment",
        arg_fields=(
            ToolFieldPresentation(
                key="attachment",
                label="Attachment",
                format="entity",
                entity_kind="outlook_attachment",
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
