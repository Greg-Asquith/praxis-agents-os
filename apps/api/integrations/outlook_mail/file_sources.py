# apps/api/integrations/outlook_mail/file_sources.py

"""Downloads an attachment a person views or saves from an Outlook message card."""

from services.integrations.plugin import (
    IntegrationFileDownload,
    IntegrationFileRequest,
    IntegrationFileSourceDefinition,
)

from .operations.copy_attachment import copy_attachment
from .references import OutlookAttachmentReference
from .tools.utils import mailbox_client_for_principal


async def download_attachment_for_person(
    db, request: IntegrationFileRequest
) -> IntegrationFileDownload:
    # The route validated the reference with this definition's reference model.
    reference = request.reference
    copied = await copy_attachment(
        await mailbox_client_for_principal(
            db, actor=request.actor, workspace=request.workspace, entry=request.scope
        ),
        message_id=reference.message_id,
        attachment_id=reference.attachment_id,
    )
    return IntegrationFileDownload(
        name=copied.name, content_type=copied.content_type, content=copied.content
    )


ATTACHMENT_FILE_SOURCE = IntegrationFileSourceDefinition(
    entity_kind="outlook_attachment",
    reference_model=OutlookAttachmentReference,
    operation="attachment_file",
    download=download_attachment_for_person,
)
