# apps/api/services/conversations/create_turn_stream.py

"""Create and stream one interactive conversation turn."""

from uuid import UUID

from fastapi import Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from models.conversation import CONVERSATION_SOURCE_DELEGATED
from models.user import User
from models.workspace import Workspace
from services.agent_runs import create_agent_run, reap_abandoned_runs
from services.agent_runs.domain import RUN_TRIGGER_INTERACTIVE
from services.agents.runtime import streaming as runtime_streaming
from services.agents.runtime.events import (
    EVENT_RUN_STATUS,
    STREAM_PROTOCOL_VERSION,
    STREAM_VERSION_HEADER,
)
from services.agents.runtime.run_manager import run_task_registry
from services.agents.runtime.sinks import StreamSink
from services.agents.runtime.worker import run_turn_worker
from services.conversations.schemas import ConversationTurnCreateRequest
from services.conversations.utils import (
    build_interactive_run_metadata,
    get_active_run_for_conversation,
    get_conversation_for_actor,
    get_message_by_client_message_id,
)

SSE_KEEPALIVE_FRAME = runtime_streaming.SSE_KEEPALIVE_FRAME
_drain_sse_sink = runtime_streaming.drain_sse_sink


async def create_conversation_turn_stream(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    conversation_id: UUID,
    payload: ConversationTurnCreateRequest,
    request: Request | None = None,
) -> StreamingResponse:
    """Create a durable run and return an SSE response for its live events."""
    conversation = await get_conversation_for_actor(
        db,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation_id,
    )
    if conversation.source == CONVERSATION_SOURCE_DELEGATED:
        raise ConflictError(
            "Delegated agent transcripts are read-only",
            conflicting_resource="conversation",
            details={"conversation_id": str(conversation.id), "source": conversation.source},
        )

    if conversation.active_agent_id is None:
        raise ConflictError(
            "Conversation has no active agent",
            conflicting_resource="conversation",
            details={"conversation_id": str(conversation.id)},
        )

    await reap_abandoned_runs(db, conversation_id=conversation.id)
    active_run = await get_active_run_for_conversation(db, conversation_id=conversation.id)
    if active_run is not None:
        raise ConflictError(
            "Conversation already has an active agent run",
            conflicting_resource="agent_run",
            details={
                "active_run_id": str(active_run.id),
                "active_run_status": active_run.status,
            },
        )

    if payload.client_message_id is not None:
        existing_message = await get_message_by_client_message_id(
            db,
            conversation_id=conversation.id,
            client_message_id=payload.client_message_id,
        )
        if existing_message is not None:
            metadata = existing_message.metadata_json or {}
            raise ConflictError(
                "Conversation already contains a message with this client_message_id",
                conflicting_resource="conversation_message",
                details={
                    "client_message_id": payload.client_message_id,
                    "existing_message_id": str(existing_message.id),
                    "existing_agent_run_id": metadata.get("agent_run_id"),
                    "existing_message_sequence": str(existing_message.sequence),
                },
            )

    run = await create_agent_run(
        db,
        conversation_id=conversation.id,
        agent_id=conversation.active_agent_id,
        workspace_id=workspace.id,
        user_id=actor.id,
        trigger=RUN_TRIGGER_INTERACTIVE,
        metadata=build_interactive_run_metadata(
            client_message_id=payload.client_message_id,
            request=request,
        ),
    )
    await db.commit()

    sink = StreamSink(run_id=run.id, conversation_id=conversation.id)
    await sink.emit(EVENT_RUN_STATUS, {"status": run.status})
    run_task_registry.spawn(
        run.id,
        run_turn_worker(
            run_id=run.id,
            conversation_id=conversation.id,
            user_prompt=payload.user_prompt,
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
