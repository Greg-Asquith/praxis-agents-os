# apps/api/integrations/outlook_mail/operations/save_attachment.py

"""Saves one Outlook file attachment as a workspace File for an agent or a person."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import Agent
from models.user import User
from models.workspace import Workspace
from services.integrations.files.create_copy import create_copy
from services.integrations.microsoft_graph import MicrosoftGraphClient

from ..references import OutlookAttachmentReference
from .copy_attachment import copy_attachment


async def save_attachment(
    db: AsyncSession,
    client: MicrosoftGraphClient,
    *,
    workspace: Workspace,
    user: User,
    conversation_id: UUID,
    reference: OutlookAttachmentReference,
    agent: Agent | None = None,
    folder: str | None = None,
):
    """The agent is the revision actor when given; otherwise the person is."""
    copied = await copy_attachment(
        client, message_id=reference.message_id, attachment_id=reference.attachment_id
    )
    return await create_copy(
        db,
        workspace=workspace,
        user=user,
        conversation_id=conversation_id,
        name=copied.name,
        content=copied.content,
        content_type=copied.content_type,
        agent=agent,
        folder=folder,
    )
