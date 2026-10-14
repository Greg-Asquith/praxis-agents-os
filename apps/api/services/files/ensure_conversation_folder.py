# apps/api/services/files/ensure_conversation_folder.py

"""Resolve the durable output folder linked to a conversation."""

from typing import TYPE_CHECKING

from models.files import FileFolder
from services.files.folder_utils import FOLDER_CONVERSATION_UNIQUE_INDEX, ensure_linked_folder

if TYPE_CHECKING:
    from services.agents.runtime.context import RuntimeDeps


async def ensure_conversation_folder(deps: "RuntimeDeps") -> FileFolder:
    return await ensure_linked_folder(
        deps,
        link=FileFolder.source_conversation_id,
        link_id=deps.conversation.id,
        link_index=FOLDER_CONVERSATION_UNIQUE_INDEX,
        name=deps.conversation.title or "New Conversation",
    )
