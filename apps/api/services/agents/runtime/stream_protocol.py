# apps/api/services/agents/runtime/stream_protocol.py

"""Authoritative models and exported artifacts for the agent stream protocol."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from services.agent_runs.domain import RunStatus
from services.agent_runs.schemas import PendingDelegatedApprovalRead
from services.conversation_read_contract import ConversationRead, ConversationSource

STREAM_PROTOCOL_VERSION = "1"
STREAM_VERSION_HEADER = "X-Praxis-Stream-Version"

type MessageChannel = Literal["text", "thinking"]
type StreamRunStatus = RunStatus | Literal["queued"]
type WorkflowState = Literal["started", "completed", "failed"]


class StreamEventPayload(BaseModel):
    """Base class for one event-specific payload before sink envelope stamping."""

    event_name: ClassVar[str]
    exclude_none: ClassVar[bool] = False

    model_config = ConfigDict(extra="forbid")

    def serialize_payload(self) -> dict[str, Any]:
        """Serialize this payload without adding fields omitted at construction."""
        return self.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=self.exclude_none,
            exclude_unset=True,
        )


class ConversationCreatedEvent(StreamEventPayload):
    event_name: ClassVar[Literal["conversation.created"]] = "conversation.created"

    conversation: ConversationRead


class ConversationUpdatedEvent(StreamEventPayload):
    event_name: ClassVar[Literal["conversation.updated"]] = "conversation.updated"

    conversation: ConversationRead


class RunStatusEvent(StreamEventPayload):
    event_name: ClassVar[Literal["run.status"]] = "run.status"

    status: StreamRunStatus


class MessageStartEvent(StreamEventPayload):
    event_name: ClassVar[Literal["message.start"]] = "message.start"

    message_id: str = Field(min_length=1)
    role: Literal["assistant"]
    channel: MessageChannel


class MessageDeltaEvent(StreamEventPayload):
    event_name: ClassVar[Literal["message.delta"]] = "message.delta"

    message_id: str = Field(min_length=1)
    text: str


class MessageEndEvent(StreamEventPayload):
    event_name: ClassVar[Literal["message.end"]] = "message.end"

    message_id: str = Field(min_length=1)


class ToolCallEvent(StreamEventPayload):
    event_name: ClassVar[Literal["tool.call"]] = "tool.call"

    tool_call_id: str = Field(min_length=1)
    parent_tool_call_id: str | None = Field(default=None, min_length=1)
    name: str = Field(min_length=1)
    args: Any


class ToolResultEvent(StreamEventPayload):
    event_name: ClassVar[Literal["tool.result"]] = "tool.result"

    tool_call_id: str = Field(min_length=1)
    parent_tool_call_id: str | None = Field(default=None, min_length=1)
    name: str | None = Field(min_length=1)
    result: Any


class TaintSource(BaseModel):
    source_kind: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")


class ToolApprovalRequiredEvent(StreamEventPayload):
    event_name: ClassVar[Literal["tool.approval_required"]] = "tool.approval_required"

    tool_call_id: str = Field(min_length=1)
    parent_tool_call_id: str | None = Field(default=None, min_length=1)
    name: str = Field(min_length=1)
    args: Any
    replay_args: Any = None
    delegation: PendingDelegatedApprovalRead | None = None
    derived_from_untrusted: bool | None = None
    taint_sources: list[TaintSource] | None = None


class WorkflowStateEvent(StreamEventPayload):
    event_name: ClassVar[Literal["workflow.state"]] = "workflow.state"

    tool_call_id: str = Field(min_length=1)
    state: WorkflowState
    output_excerpt: str | None = None
    error_excerpt: str | None = None


class ErrorEvent(StreamEventPayload):
    event_name: ClassVar[Literal["error"]] = "error"

    code: str = Field(min_length=1)
    message: str


class DoneEvent(StreamEventPayload):
    event_name: ClassVar[Literal["done"]] = "done"

    status: RunStatus


STREAM_EVENT_MODELS: tuple[type[StreamEventPayload], ...] = (
    ConversationCreatedEvent,
    ConversationUpdatedEvent,
    RunStatusEvent,
    MessageStartEvent,
    MessageDeltaEvent,
    MessageEndEvent,
    ToolCallEvent,
    ToolResultEvent,
    ToolApprovalRequiredEvent,
    WorkflowStateEvent,
    ErrorEvent,
    DoneEvent,
)


def serialize_stream_payload(payload: StreamEventPayload) -> dict[str, Any]:
    """Serialize a typed payload without adding fields omitted at construction."""
    return payload.serialize_payload()


def _enum_values(annotation: Any) -> list[str]:
    schema = TypeAdapter(annotation).json_schema()
    definitions = schema.get("$defs", {})
    values: list[str] = []

    def collect(node: dict[str, Any]) -> None:
        reference = node.get("$ref")
        if isinstance(reference, str):
            definition = definitions.get(reference.rsplit("/", maxsplit=1)[-1])
            if isinstance(definition, dict):
                collect(definition)
            return
        if "enum" in node:
            values.extend(value for value in node["enum"] if isinstance(value, str))
        elif isinstance(node.get("const"), str):
            values.append(node["const"])
        for alternative in node.get("anyOf", []):
            collect(alternative)

    collect(schema)
    if not values:
        raise ValueError(f"Stream protocol enum {annotation!r} has no string values")
    return values


def stream_protocol_schema() -> dict[str, Any]:
    """Return the checked-in browser contract derived from the Python models."""
    envelope_properties = {
        "run_id": {"type": "string", "minLength": 1},
        "conversation_id": {"type": "string", "minLength": 1},
        "seq": {"type": "integer", "minimum": 1},
    }
    events: dict[str, Any] = {}
    for model in STREAM_EVENT_MODELS:
        schema = model.model_json_schema(mode="serialization", by_alias=True)
        schema["properties"] = {**envelope_properties, **schema.get("properties", {})}
        schema["required"] = [
            "run_id",
            "conversation_id",
            "seq",
            *schema.get("required", []),
        ]
        events[model.event_name] = schema

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Praxis agent stream protocol",
        "version": STREAM_PROTOCOL_VERSION,
        "header": STREAM_VERSION_HEADER,
        "event_names": [model.event_name for model in STREAM_EVENT_MODELS],
        "enums": {
            "agent_run_statuses": _enum_values(RunStatus),
            "stream_run_statuses": _enum_values(StreamRunStatus),
            "conversation_sources": _enum_values(ConversationSource),
            "message_channels": _enum_values(MessageChannel),
            "workflow_states": _enum_values(WorkflowState),
        },
        "events": events,
    }


def stream_protocol_samples() -> list[dict[str, Any]]:
    """Return one representative browser frame for every stream event."""
    sample_uuid = UUID("11111111-1111-4111-8111-111111111111")
    conversation = ConversationRead(
        id=sample_uuid,
        user_id=sample_uuid,
        workspace_id=sample_uuid,
        created_by=sample_uuid,
        title="Sample conversation",
        description=None,
        status="active",
        metadata_json=None,
        unread=False,
        source="direct",
        last_message_at=None,
        active_agent_id=sample_uuid,
        agent_slug="sample-agent",
        agent_name="Sample agent",
        active_run_id=sample_uuid,
        active_run_status="running",
        needs_approval=False,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    payloads: tuple[StreamEventPayload, ...] = (
        ConversationCreatedEvent(conversation=conversation),
        ConversationUpdatedEvent(conversation=conversation),
        RunStatusEvent(status="queued"),
        MessageStartEvent(
            message_id="run:assistant:1",
            role="assistant",
            channel="thinking",
        ),
        MessageDeltaEvent(message_id="run:assistant:1", text="Sample delta"),
        MessageEndEvent(message_id="run:assistant:1"),
        ToolCallEvent(
            tool_call_id="nested-call",
            name="sample_tool",
            args=None,
            parent_tool_call_id="workflow-call",
        ),
        ToolResultEvent(
            tool_call_id="nested-call",
            name=None,
            result={"status": "completed"},
            parent_tool_call_id="workflow-call",
        ),
        ToolApprovalRequiredEvent(
            tool_call_id="nested-call",
            name="sample_tool",
            args={"query": "sample"},
            replay_args={"query": "sample"},
            parent_tool_call_id="workflow-call",
            delegation=PendingDelegatedApprovalRead(
                parent_tool_call_id="workflow-call",
                child_agent_id=sample_uuid,
                child_agent_name="Research agent",
                child_conversation_id=sample_uuid,
                child_run_id=sample_uuid,
                pending_approval_count=1,
            ),
            derived_from_untrusted=True,
            taint_sources=[TaintSource(source_kind="web", source_ref="https://example.com")],
        ),
        WorkflowStateEvent(
            tool_call_id="workflow-call",
            state="completed",
            output_excerpt="Sample output",
        ),
        ErrorEvent(code="sample_error", message="Sample error"),
        DoneEvent(status="completed"),
    )
    envelope = {
        "run_id": str(sample_uuid),
        "conversation_id": str(sample_uuid),
    }
    return [
        {
            "event": payload.event_name,
            "data": {**envelope, "seq": index, **serialize_stream_payload(payload)},
        }
        for index, payload in enumerate(payloads, start=1)
    ]
