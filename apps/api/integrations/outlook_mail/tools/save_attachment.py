# apps/api/integrations/outlook_mail/tools/save_attachment.py

"""Saves one Outlook file attachment's original bytes as a workspace File."""

from typing import Annotated

from pydantic import Field
from pydantic_ai import RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_INTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_PROVIDER_QUERY,
    TOOL_POLICY_AUTO,
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
from services.integrations.context.targeted import run_context_targets
from services.integrations.files import FileReference
from services.integrations.files.create_copy import create_copy
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.copy_attachment import copy_attachment
from ..operations.utils import untrusted
from ..references import OutlookAttachmentReference
from .schemas import SavedAttachmentData, SavedAttachmentOutput
from .utils import (
    OUTLOOK_MAIL_BINDING,
    RESULTS_FIELD,
    bounded_output,
    mailbox_client,
    outlook_mail_available,
)


# The Field description keeps the `attachment` wrapper in the model-facing schema; see read_message.
async def outlook_mail_save_attachment(
    ctx: RunContext[RuntimeDeps],
    attachment: Annotated[
        OutlookAttachmentReference,
        Field(description="Scoped Outlook attachment reference returned by reading a message."),
    ],
    folder: Annotated[str | None, Field(max_length=255)] = None,
) -> dict:
    async def operation(entry, references):
        reference = references[0]

        async def execute():
            client = await mailbox_client(ctx, entry)
            copied = await copy_attachment(
                client, message_id=reference.message_id, attachment_id=reference.attachment_id
            )
            saved = await create_copy(
                ctx.deps,
                name=copied.name,
                content=copied.content,
                content_type=copied.content_type,
                folder=folder,
            )
            detail = terminal_applied_operation_detail(
                PendingIntegrationOperationDetail(
                    target=IntegrationOperationTarget(
                        entity_type="outlook_attachment",
                        external_id=reference.attachment_id,
                        attributes={
                            "mailbox_id": entry.external_id,
                            "message_id": reference.message_id,
                        },
                    ),
                    intent_groups=[
                        IntegrationOperationIntentGroup(
                            key="save_attachment",
                            action="save_attachment",
                            entity_type="file",
                            items=[
                                IntegrationOperationIntent(
                                    fields={"attachment_id": reference.attachment_id}
                                )
                            ],
                        )
                    ],
                ),
                external_ref=str(saved.file.id),
            )
            detail.outcome_groups[0].outcomes[0].effects[0].fields.update(
                file_id=str(saved.file.id), revision_id=str(saved.revision.id)
            )
            result = SavedAttachmentData(
                reference=FileReference(entity_id=saved.file.id, label="Saved Outlook attachment"),
                file_id=saved.file.id,
                revision_id=saved.revision.id,
                name=untrusted(reference.message_id, saved.file.name),
                content_type=copied.content_type,
                size_bytes=saved.bytes_written,
                attachment=reference,
            )
            return IntegrationAuditOutcome(
                result.model_dump(),
                external_ref=reference.provider_entity_id,
                operation_detail=detail,
            )

        async with ctx.deps.db.begin_nested():
            return await run_audited_integration_operation(
                ctx,
                entry,
                tool_name="outlook_mail_save_attachment",
                operation="save_attachment",
                execute=execute,
            )

    return bounded_output(
        await run_context_targets(
            ctx, binding=OUTLOOK_MAIL_BINDING, references=[attachment], operation=operation
        )
    )


DEFINITION = RuntimeToolDefinition(
    name="outlook_mail_save_attachment",
    function=outlook_mail_save_attachment,
    description=(
        "Saves the original bytes of one Outlook file attachment as a new workspace File, using "
        "its attachment reference from reading a message. Supports the Files document, text, "
        "image, video, and audio types within their size limits; embedded emails and linked "
        "attachments are unsupported. Optionally save into a named folder, creating it if needed. "
        "Returns a File reference for the document and file tools. The original bytes stay out "
        "of model context."
    ),
    provider="outlook_mail",
    label="Save Attachment to Files",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_INTERNAL,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    default_policy=TOOL_POLICY_AUTO,
    supports_auto=True,
    supports_approval=True,
    takes_ctx=True,
    timeout=120,
    output_model=SavedAttachmentOutput,
    integration_binding=OUTLOOK_MAIL_BINDING,
    availability_check=outlook_mail_available,
    presentation=ToolPresentation(
        icon="outlook_mail",
        running_label="Saving Outlook attachment to Files",
        completed_label="Saved Outlook attachment to Files",
        failed_label="Could not save Outlook attachment to Files",
        approval_title="Save Attachment to Files",
        approval_prompt="Save a copy of this Outlook attachment in your workspace Files.",
        approve_label="Approve & Save",
        arg_fields=(
            ToolFieldPresentation(
                key="attachment",
                label="Attachment",
                format="entity",
                entity_kind="outlook_attachment",
            ),
            ToolFieldPresentation(key="folder", label="Folder", editable=True, secondary=True),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
