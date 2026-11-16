# apps/api/integrations/outlook_mail/tools/find_in_attachment.py

"""Find literal text in one referenced Outlook attachment."""

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

from ..operations.find_in_attachment import OPERATION, find_in_attachment
from ..references import OutlookAttachmentReference
from .schemas import AttachmentFindOutput
from .utils import (
    OUTLOOK_MAIL_BINDING,
    RESULTS_FIELD,
    bounded_output,
    mailbox_client,
    outlook_mail_available,
)


# The Field description keeps the `attachment` wrapper in the model-facing schema; see read_message.
async def outlook_mail_find_in_attachment(
    ctx: RunContext[RuntimeDeps],
    attachment: Annotated[
        OutlookAttachmentReference,
        Field(description="Scoped Outlook attachment reference returned by reading a message."),
    ],
    query: Annotated[str, Field(min_length=1, max_length=200)],
    limit: Annotated[int, Field(ge=1, le=25)] = 10,
) -> dict:
    async def operation(entry, references):
        reference = references[0]

        async def execute():
            client = await mailbox_client(ctx, entry)
            return IntegrationAuditOutcome(
                await find_in_attachment(
                    client,
                    message_id=reference.message_id,
                    attachment_id=reference.attachment_id,
                    query=query,
                    limit=limit,
                ),
                external_ref=reference.provider_entity_id,
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="outlook_mail_find_in_attachment",
            operation=OPERATION,
            execute=execute,
        )

    return bounded_output(
        await run_context_targets(
            ctx, binding=OUTLOOK_MAIL_BINDING, references=[attachment], operation=operation
        )
    )


DEFINITION = RuntimeToolDefinition(
    name="outlook_mail_find_in_attachment",
    function=outlook_mail_find_in_attachment,
    description=(
        "Use first when looking for specific information in an Outlook file attachment, such "
        "as what a person says, a figure, a date, or a clause, instead of reading it from the "
        "start. Searches the whole attachment for case-insensitive literal text and returns up "
        "to 25 excerpts with byte offsets. Search for a distinctive word or name rather than a "
        "full sentence. Pass an excerpt's offset to outlook_mail_read_attachment to read the "
        "surrounding content."
    ),
    provider="outlook_mail",
    label="Find in Outlook Attachment",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    default_policy=TOOL_POLICY_AUTO,
    takes_ctx=True,
    timeout=60,
    output_model=AttachmentFindOutput,
    integration_binding=OUTLOOK_MAIL_BINDING,
    availability_check=outlook_mail_available,
    presentation=ToolPresentation(
        icon="outlook_mail",
        running_label="Finding text in Outlook attachment",
        completed_label="Found text in Outlook attachment",
        failed_label="Could not find text in Outlook attachment",
        arg_fields=(
            ToolFieldPresentation(
                key="attachment",
                label="Attachment",
                format="entity",
                entity_kind="outlook_attachment",
            ),
            ToolFieldPresentation(key="query", label="Query", format="text"),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
