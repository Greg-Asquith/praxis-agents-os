# apps/api/services/agents/runtime/events.py

"""Runtime event names and Pydantic AI event translation."""

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    NativeToolCallPart,
    NativeToolReturnPart,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    RetryPromptPart,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_core import to_jsonable_python

from services.agents.runtime.sinks import EventSink

type MessageChannel = Literal["text", "thinking"]

EVENT_RUN_STATUS = "run.status"
EVENT_MESSAGE_START = "message.start"
EVENT_MESSAGE_DELTA = "message.delta"
EVENT_MESSAGE_END = "message.end"
EVENT_TOOL_CALL = "tool.call"
EVENT_TOOL_RESULT = "tool.result"
EVENT_TOOL_APPROVAL_REQUIRED = "tool.approval_required"
EVENT_WORKFLOW_STATE = "workflow.state"
EVENT_CONVERSATION_CREATED = "conversation.created"
EVENT_CONVERSATION_UPDATED = "conversation.updated"
EVENT_ERROR = "error"
EVENT_DONE = "done"

STREAM_PROTOCOL_VERSION = "1"
STREAM_VERSION_HEADER = "X-Praxis-Stream-Version"


@dataclass
class EventTranslationState:
    """Tracks active assistant message ids while translating a stream."""

    next_message_index: int = 0
    active_messages: dict[int, tuple[str, MessageChannel]] = field(default_factory=dict)
    native_tool_calls: dict[str, NativeToolCallPart] = field(default_factory=dict)

    def start_message(self, part_index: int, run_id: str, channel: MessageChannel) -> str:
        self.next_message_index += 1
        message_id = f"{run_id}:assistant:{self.next_message_index}"
        self.active_messages[part_index] = (message_id, channel)
        return message_id

    def active_message(self, part_index: int) -> str | None:
        active_message = self.active_messages.get(part_index)
        if active_message is None:
            return None
        return active_message[0]

    def end_message(self, part_index: int) -> str | None:
        active_message = self.active_messages.pop(part_index, None)
        if active_message is None:
            return None
        return active_message[0]


async def emit_agent_stream_event(
    sink: EventSink,
    event: Any,
    *,
    run_id: str,
    state: EventTranslationState,
) -> None:
    """Translate one Pydantic AI stream event into the Praxis runtime event contract."""
    if isinstance(event, PartStartEvent) and isinstance(event.part, (TextPart, ThinkingPart)):
        channel: MessageChannel = "thinking" if isinstance(event.part, ThinkingPart) else "text"
        message_id = state.start_message(event.index, run_id, channel)
        await sink.emit(
            EVENT_MESSAGE_START,
            {"message_id": message_id, "role": "assistant", "channel": channel},
        )
        if event.part.content:
            await sink.emit(
                EVENT_MESSAGE_DELTA,
                {"message_id": message_id, "text": event.part.content},
            )
        return

    if isinstance(event, PartStartEvent) and isinstance(event.part, NativeToolCallPart):
        part = event.part
        await sink.emit(
            EVENT_TOOL_CALL,
            {
                "tool_call_id": part.tool_call_id,
                "name": part.tool_name,
                "args": to_jsonable_python(part.args),
            },
        )
        return

    if isinstance(event, PartStartEvent) and isinstance(event.part, ToolCallPart):
        part = event.part
        await sink.emit(
            EVENT_TOOL_CALL,
            {
                "tool_call_id": part.tool_call_id,
                "name": part.tool_name,
                # Function-tool arguments may be very large and are incomplete at
                # part start. Emit the identity now so clients can show progress;
                # FunctionToolCallEvent replaces this with validated arguments.
                "args": None,
            },
        )
        return

    if isinstance(event, PartStartEvent) and isinstance(event.part, NativeToolReturnPart):
        part = event.part
        await sink.emit(
            EVENT_TOOL_RESULT,
            {
                "tool_call_id": part.tool_call_id,
                "name": part.tool_name,
                "result": to_jsonable_python(part.content),
            },
        )
        return

    if isinstance(event, PartDeltaEvent):
        if not isinstance(event.delta, (TextPartDelta, ThinkingPartDelta)):
            return
        text_delta = event.delta.content_delta
        message_id = state.active_message(event.index)
        if message_id is not None and text_delta:
            await sink.emit(
                EVENT_MESSAGE_DELTA,
                {"message_id": message_id, "text": text_delta},
            )
        return

    if isinstance(event, PartEndEvent):
        message_id = state.end_message(event.index)
        if message_id is not None:
            await sink.emit(EVENT_MESSAGE_END, {"message_id": message_id})
        return

    if isinstance(event, FunctionToolCallEvent):
        part = event.part
        await sink.emit(
            EVENT_TOOL_CALL,
            {
                "tool_call_id": part.tool_call_id,
                "name": part.tool_name,
                "args": to_jsonable_python(part.args),
            },
        )
        return

    if isinstance(event, FunctionToolResultEvent):
        part = event.part
        await sink.emit(
            EVENT_TOOL_RESULT,
            {
                "tool_call_id": part.tool_call_id,
                "name": part.tool_name,
                "result": public_function_tool_result(part),
            },
        )


def public_function_tool_result(part: ToolReturnPart | RetryPromptPart) -> Any:
    """Return a stream-safe tool result without multimodal transport bytes."""
    if (
        isinstance(part, ToolReturnPart)
        and isinstance(part.metadata, dict)
        and "public_result" in part.metadata
    ):
        return to_jsonable_python(part.metadata["public_result"])
    if isinstance(part, ToolReturnPart) and part.files:
        return part.model_response_object()
    return to_jsonable_python(part.content)
