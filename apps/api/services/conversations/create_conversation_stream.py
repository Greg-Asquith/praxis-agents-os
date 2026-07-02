# apps/api/services/conversations/create_conversation_stream.py

"""Create a conversation and stream its first interactive turn."""

import asyncio
import logging
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import configure_async_db_session, get_async_db_session_factory
from models.conversation import CONVERSATION_SOURCE_DIRECT, Conversation
from models.user import User
from models.workspace import Workspace
from services.agent_runs import create_agent_run
from services.agent_runs.domain import RUN_TRIGGER_INTERACTIVE
from services.agents.runtime import streaming as runtime_streaming
from services.agents.runtime.events import (
    EVENT_CONVERSATION_CREATED,
    EVENT_RUN_STATUS,
    STREAM_PROTOCOL_VERSION,
    STREAM_VERSION_HEADER,
)
from services.agents.runtime.run_manager import run_task_registry
from services.agents.runtime.sinks import StreamSink
from services.agents.runtime.worker import run_turn_worker
from services.conversations.naming import (
    ConversationTitle,
    fallback_conversation_title,
    run_conversation_title_worker,
)
from services.conversations.prune_failed import prune_failed_empty_conversation_for_run
from services.conversations.schemas import ConversationCreateRequest, ConversationRead
from services.conversations.utils import get_assignable_agent_for_workspace

_drain_sse_sink = runtime_streaming.drain_sse_sink
logger = logging.getLogger(__name__)

TITLE_UPDATE_STREAM_WAIT_SECONDS = 2.0
_background_title_tasks: set[asyncio.Task[None]] = set()


async def create_conversation_stream(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    payload: ConversationCreateRequest,
) -> StreamingResponse:
    """Create a conversation, create its first run, and return an SSE response."""
    agent = await get_assignable_agent_for_workspace(
        db,
        workspace=workspace,
        agent_id=payload.agent_id,
    )
    agent_id = agent.id
    agent_slug = agent.slug
    # Close the read-only validation transaction before the external naming call.
    await db.commit()

    title = ConversationTitle(
        title=fallback_conversation_title(payload.user_prompt),
        source="fallback",
        model_name=None,
    )

    conversation = Conversation(
        user_id=actor.id,
        workspace_id=workspace.id,
        created_by=actor.id,
        source=CONVERSATION_SOURCE_DIRECT,
        title=title.title,
        active_agent_id=agent_id,
        agent_slug=agent_slug,
        metadata_json=_title_metadata(title),
    )
    db.add(conversation)
    await db.flush()

    run = await create_agent_run(
        db,
        conversation_id=conversation.id,
        agent_id=agent_id,
        workspace_id=workspace.id,
        user_id=actor.id,
        trigger=RUN_TRIGGER_INTERACTIVE,
        metadata={"client_message_id": payload.client_message_id}
        if payload.client_message_id
        else None,
    )
    await db.commit()

    sink = StreamSink(run_id=run.id, conversation_id=conversation.id)
    await sink.emit(
        EVENT_CONVERSATION_CREATED,
        {
            "conversation": ConversationRead.from_projection(
                conversation,
                agent_name=agent.name,
                active_run_id=run.id,
                active_run_status=run.status,
            ).model_dump(mode="json", by_alias=True)
        },
    )
    await sink.emit(EVENT_RUN_STATUS, {"status": run.status})
    run_task_registry.spawn(
        run.id,
        _run_initial_conversation_worker(
            run_id=run.id,
            conversation_id=conversation.id,
            actor_id=actor.id,
            user_prompt=payload.user_prompt,
            fallback_title=title.title,
            sink=sink,
            client_message_id=payload.client_message_id,
        ),
    )

    return StreamingResponse(
        _drain_sse_sink(sink),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            STREAM_VERSION_HEADER: STREAM_PROTOCOL_VERSION,
            "X-Accel-Buffering": "no",
        },
    )


async def _run_initial_conversation_worker(
    *,
    run_id: UUID,
    conversation_id: UUID,
    actor_id: UUID,
    user_prompt: str,
    fallback_title: str,
    sink: StreamSink,
    client_message_id: str | None,
) -> None:
    title_task = _spawn_title_task(
        run_conversation_title_worker(
            conversation_id=conversation_id,
            user_prompt=user_prompt,
            fallback_title=fallback_title,
            sink=sink,
        ),
        name=f"conversation-title:{conversation_id}",
    )
    title_update_sink = _CloseAfterTitleTaskSink(
        sink,
        title_task,
        wait_timeout_seconds=TITLE_UPDATE_STREAM_WAIT_SECONDS,
    )
    await run_turn_worker(
        run_id=run_id,
        conversation_id=conversation_id,
        user_prompt=user_prompt,
        sink=title_update_sink,
        client_message_id=client_message_id,
    )
    await _prune_failed_initial_conversation(
        run_id=run_id,
        conversation_id=conversation_id,
        actor_id=actor_id,
    )


async def _prune_failed_initial_conversation(
    *,
    run_id: UUID,
    conversation_id: UUID,
    actor_id: UUID,
) -> None:
    session_factory = get_async_db_session_factory()
    session = session_factory()
    try:
        await configure_async_db_session(session)
        await prune_failed_empty_conversation_for_run(
            session,
            conversation_id=conversation_id,
            run_id=run_id,
            deleted_by_user_id=actor_id,
        )
        await session.commit()
    except Exception:
        await session.rollback()
        logger.warning(
            "Failed to prune empty initial conversation",
            exc_info=True,
            extra={"run_id": str(run_id), "conversation_id": str(conversation_id)},
        )
    finally:
        await session.close()


def _spawn_title_task(coro, *, name: str) -> asyncio.Task[None]:
    task = asyncio.create_task(coro, name=name)
    _background_title_tasks.add(task)
    task.add_done_callback(_background_title_tasks.discard)
    return task


class _CloseAfterTitleTaskSink:
    """Forward terminal events immediately, then briefly keep the stream open for title updates."""

    def __init__(
        self,
        delegate: StreamSink,
        pending_task: asyncio.Task[None],
        *,
        wait_timeout_seconds: float,
    ):
        self._delegate = delegate
        self._pending_task = pending_task
        self._wait_timeout_seconds = wait_timeout_seconds
        self._waited = False

    async def emit(self, event: str, payload: Mapping[str, Any] | None = None) -> None:
        await self._delegate.emit(event, payload)

    async def close(self) -> None:
        await self._wait_for_pending_task()
        await self._delegate.close()

    async def _wait_for_pending_task(self) -> None:
        if self._waited:
            return
        self._waited = True
        try:
            await asyncio.wait_for(
                asyncio.shield(self._pending_task),
                timeout=self._wait_timeout_seconds,
            )
        except TimeoutError:
            logger.warning("Timed out waiting for conversation title update before closing stream")
        except Exception:
            logger.warning("Conversation title task failed before stream close", exc_info=True)


def _title_metadata(title: ConversationTitle) -> dict[str, object]:
    title_metadata: dict[str, object] = {"source": title.source}
    if title.model_name:
        title_metadata["model"] = title.model_name
    return {"title": title_metadata}
