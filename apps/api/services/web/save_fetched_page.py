# apps/api/services/web/save_fetched_page.py

"""Fetch a page again and save it into Files as the signed-in person, with no agent turn."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from core.settings import settings
from models.user import User
from models.workspace import Workspace
from services.audit_events import AuditAction, AuditActorType, AuditResourceType
from services.audit_events.operations import record_operation_audit_event
from services.conversations.utils import get_conversation_for_actor
from services.integrations.files.create_copy import create_copy
from services.web.fetch import fetch_url
from services.web.schemas import FetchedPageSaveRead
from services.web.utils import configured_blocked_domains, file_content_type, page_file_name


async def save_fetched_page(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    conversation_id: UUID,
    url: str,
) -> FetchedPageSaveRead:
    """Saves the page as it is now, so it can differ from what the agent read.

    Raises:
        NotFoundError: If the conversation isn't the person's own in this workspace.
        AppValidationError: If the fetch is refused or fails, or the response isn't a
            successful text or document body.
    """
    conversation = await get_conversation_for_actor(
        db, actor=actor, workspace=workspace, conversation_id=conversation_id
    )
    response = await fetch_url(
        url,
        timeout_seconds=settings.WEB_FETCH_TIMEOUT_SECONDS,
        max_redirects=settings.WEB_FETCH_MAX_REDIRECTS,
        max_bytes=settings.WEB_FETCH_MAX_BYTES,
        body="success",
        gunzip=True,
        standard_ports_only=True,
        blocked_domains=configured_blocked_domains(),
    )
    content_type = file_content_type(response)
    if content_type is None:
        raise AppValidationError(
            "Only a page or document that loads successfully can be saved to Files",
            field="url",
            details={"status": response.status},
        )
    saved = await create_copy(
        db,
        workspace=workspace,
        user=actor,
        conversation_id=conversation.id,
        name=page_file_name(response.requested_url),
        content=response.body,
        content_type=content_type,
    )
    await record_operation_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.CREATE,
        resource_type=AuditResourceType.FILE,
        resource_id=saved.file.id,
        actor_type=AuditActorType.USER,
        actor_id=actor.id,
        actor_display=actor.email,
        requested_by_user_id=actor.id,
        details={
            "operation": "save_fetched_page",
            "conversation_id": str(conversation.id),
            "revision_id": str(saved.revision.id),
            "url": response.final_url[:2_048],
        },
    )
    result = FetchedPageSaveRead(
        file_id=saved.file.id,
        name=saved.file.name,
        content_type=saved.file.content_type,
        size_bytes=saved.bytes_written,
    )
    await db.commit()
    return result
