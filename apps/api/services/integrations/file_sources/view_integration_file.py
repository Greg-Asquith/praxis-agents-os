# apps/api/services/integrations/file_sources/view_integration_file.py

"""Return one provider file's bytes for a person to view, without saving a copy."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationValidationError
from models.user import User
from models.workspace import Workspace
from services.audit_events import AuditAction
from services.files.contract import FileCategory, contract_for_content_type
from services.integrations.file_sources.schemas import IntegrationFileSourceCreate
from services.integrations.file_sources.utils import (
    record_file_request_failure,
    resolve_file_request,
)
from services.integrations.plugin import IntegrationFileDownload

# Types a browser shows safely from a blob; documents need saving to open.
VIEWABLE_CATEGORIES = frozenset({FileCategory.IMAGE, FileCategory.VIDEO, FileCategory.AUDIO})
VIEWABLE_CONTENT_TYPES = frozenset({"application/pdf"})


async def view_integration_file(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    conversation_id: UUID,
    payload: IntegrationFileSourceCreate,
) -> IntegrationFileDownload:
    """Successful views stay unaudited, like previews; the tool call that listed the file has one."""
    definition, file_request = await resolve_file_request(
        db, actor=actor, workspace=workspace, conversation_id=conversation_id, payload=payload
    )
    await db.commit()
    try:
        download = await definition.download(db, file_request)
        contract = contract_for_content_type(download.content_type)
        if (
            contract.category not in VIEWABLE_CATEGORIES
            and contract.content_type not in VIEWABLE_CONTENT_TYPES
        ):
            raise IntegrationValidationError(
                "This file type can't be viewed here. Save it to Files to open it.",
                provider_key=payload.provider_key,
                operation=definition.operation,
                error_code="unviewable_file_type",
            )
    except Exception as exc:
        await record_file_request_failure(
            request=file_request,
            action=AuditAction.READ,
            operation=definition.operation,
            conversation_id=conversation_id,
            exc=exc,
        )
        raise
    return download
