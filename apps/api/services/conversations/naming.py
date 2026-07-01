# apps/api/services/conversations/naming.py

"""Generate short conversation titles with structured model output."""

import logging
from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models import Model
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import configure_async_db_session, get_async_db_session_factory
from models.conversation import Conversation
from services.agents.models import build_model, resolve_naming_model
from services.agents.runtime.events import EVENT_CONVERSATION_UPDATED
from services.agents.runtime.sinks import EventSink
from services.conversations.schemas import ConversationRead

TITLE_MAX_LENGTH = 80

logger = logging.getLogger(__name__)

_TITLE_INSTRUCTIONS = """\
Write a concise chat title for the user's first message.
Use six words or fewer.
Do not wrap the title in quotes.
"""


@dataclass(frozen=True)
class ConversationTitle:
    title: str
    source: str
    model_name: str | None = None


class ConversationTitleOutput(BaseModel):
    title: str = Field(
        description="A concise title for the conversation, six words or fewer.",
        max_length=TITLE_MAX_LENGTH * 2,
    )


async def generate_conversation_title(
    user_prompt: str,
    *,
    model: Model | None = None,
) -> ConversationTitle:
    """Generate a short title for a new conversation with structured output."""
    resolved_model = None if model is not None else resolve_naming_model()
    naming_model = model or build_model(resolved_model)
    agent = Agent(
        naming_model,
        name="conversation_title_generator",
        output_type=ConversationTitleOutput,
        instructions=_TITLE_INSTRUCTIONS,
    )
    result = await agent.run(user_prompt)
    title = _normalize_title(result.output.title)
    if not title:
        title = fallback_conversation_title(user_prompt)
        return ConversationTitle(title=title, source="fallback", model_name=result.response.model_name)
    return ConversationTitle(title=title, source="model", model_name=result.response.model_name)


async def run_conversation_title_worker(
    *,
    conversation_id: UUID,
    user_prompt: str,
    fallback_title: str,
    sink: EventSink,
) -> None:
    """Generate and persist a better title after the create stream is open."""
    session_factory = get_async_db_session_factory()
    session = session_factory()
    try:
        await configure_async_db_session(session)
        title = await _safe_generate_title(user_prompt, fallback_title=fallback_title)
        await _persist_title_update(
            session,
            conversation_id=conversation_id,
            title=title,
            fallback_title=fallback_title,
            sink=sink,
        )
    except Exception:
        await session.rollback()
        logger.warning(
            "Conversation title update failed",
            exc_info=True,
            extra={"conversation_id": str(conversation_id)},
        )
    finally:
        await session.close()


def fallback_conversation_title(user_prompt: str) -> str:
    """Deterministic local title used when model naming is unavailable."""
    first_line = " ".join(user_prompt.split())
    return _truncate_title(first_line or "New conversation")


async def _safe_generate_title(user_prompt: str, *, fallback_title: str) -> ConversationTitle:
    try:
        return await generate_conversation_title(user_prompt)
    except Exception:
        logger.warning("Conversation title generation failed", exc_info=True)
        return ConversationTitle(title=fallback_title, source="fallback", model_name=None)


async def _persist_title_update(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    title: ConversationTitle,
    fallback_title: str,
    sink: EventSink,
) -> None:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None or conversation.deleted:
        await db.rollback()
        return
    if title.title == fallback_title and title.source == "fallback":
        await db.rollback()
        return

    metadata = dict(conversation.metadata_json or {})
    title_metadata: dict[str, object] = {"source": title.source}
    if title.model_name:
        title_metadata["model"] = title.model_name
    metadata["title"] = title_metadata

    conversation.title = title.title
    conversation.metadata_json = metadata
    await db.commit()
    await db.refresh(conversation)
    await sink.emit(
        EVENT_CONVERSATION_UPDATED,
        {
            "conversation": ConversationRead.from_conversation(conversation).model_dump(
                mode="json",
                by_alias=True,
            )
        },
    )


def _normalize_title(value: str) -> str:
    title = " ".join(value.split()).strip(" \t\r\n\"'`")
    title = title.rstrip(".")
    return _truncate_title(title)


def _truncate_title(value: str) -> str:
    if len(value) <= TITLE_MAX_LENGTH:
        return value
    return value[: TITLE_MAX_LENGTH - 3].rstrip() + "..."
