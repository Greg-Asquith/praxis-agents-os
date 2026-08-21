# apps/api/tests/contract/test_stream_protocol.py

"""Drift and wire-compatibility checks for the agent stream protocol."""

import json
from pathlib import Path
from uuid import UUID

import pytest

from services.agents.runtime.events import EVENT_TOOL_RESULT, EVENT_WORKFLOW_STATE
from services.agents.runtime.sinks import SinkEvent, StreamSink, format_sse_event
from services.agents.runtime.stream_protocol import (
    STREAM_EVENT_MODELS,
    StreamEventPayload,
    ToolResultEvent,
    WorkflowStateEvent,
    stream_protocol_samples,
    stream_protocol_schema,
)

WEB_CONTRACT_DIRECTORY = (
    Path(__file__).resolve().parents[3]
    / "web"
    / "tests"
    / "features"
    / "conversations"
    / "stream"
    / "fixtures"
)


def _load_json(filename: str) -> object:
    return json.loads((WEB_CONTRACT_DIRECTORY / filename).read_text(encoding="utf-8"))


def test_checked_in_stream_protocol_artifacts_match_backend_models() -> None:
    message = "Run `make stream-protocol-export` from the repository root."
    assert _load_json("protocol.schema.json") == stream_protocol_schema(), message
    assert _load_json("protocol.samples.json") == stream_protocol_samples(), message


def test_stream_protocol_exports_one_sample_for_every_event() -> None:
    schema = stream_protocol_schema()
    samples = stream_protocol_samples()

    event_names = [model.event_name for model in STREAM_EVENT_MODELS]
    assert schema["event_names"] == event_names
    assert list(schema["events"]) == event_names
    assert [sample["event"] for sample in samples] == event_names


def test_exported_enums_match_their_event_field_schemas() -> None:
    schema = stream_protocol_schema()
    events = schema["events"]

    assert schema["enums"]["agent_run_statuses"] == _schema_enum_values(
        events["done"], events["done"]["properties"]["status"]
    )
    assert schema["enums"]["stream_run_statuses"] == _schema_enum_values(
        events["run.status"], events["run.status"]["properties"]["status"]
    )
    assert schema["enums"]["conversation_sources"] == _schema_enum_values(
        events["conversation.created"],
        events["conversation.created"]["$defs"]["ConversationRead"]["properties"]["source"],
    )
    assert schema["enums"]["message_channels"] == _schema_enum_values(
        events["message.start"], events["message.start"]["properties"]["channel"]
    )
    assert schema["enums"]["workflow_states"] == _schema_enum_values(
        events["workflow.state"], events["workflow.state"]["properties"]["state"]
    )


def _schema_enum_values(root: dict[str, object], value: object) -> list[str]:
    if not isinstance(value, dict):
        return []
    reference = value.get("$ref")
    if isinstance(reference, str):
        definitions = root.get("$defs")
        assert isinstance(definitions, dict)
        return _schema_enum_values(root, definitions[reference.rsplit("/", maxsplit=1)[-1]])
    values = [item for item in value.get("enum", []) if isinstance(item, str)]
    constant = value.get("const")
    if isinstance(constant, str):
        values.append(constant)
    for alternative in value.get("anyOf", []):
        values.extend(_schema_enum_values(root, alternative))
    return values


@pytest.mark.asyncio
async def test_every_typed_payload_matches_its_checked_wire_sample() -> None:
    run_id = UUID("11111111-1111-4111-8111-111111111111")
    conversation_id = run_id
    checked_samples = _load_json("protocol.samples.json")
    assert isinstance(checked_samples, list)
    sink = StreamSink(run_id=run_id, conversation_id=conversation_id)

    for model, sample in zip(STREAM_EVENT_MODELS, checked_samples, strict=True):
        assert isinstance(sample, dict)
        event_name = sample["event"]
        data = sample["data"]
        assert isinstance(data, dict)
        payload_data = {
            key: value
            for key, value in data.items()
            if key not in {"run_id", "conversation_id", "seq"}
        }
        conversation = payload_data.get("conversation")
        if isinstance(conversation, dict) and "metadata" in conversation:
            conversation = {**conversation, "metadata_json": conversation["metadata"]}
            del conversation["metadata"]
            payload_data["conversation"] = conversation
        payload = model.model_validate(payload_data)
        await sink.emit(payload)
        frame = await sink.next_frame()

        assert frame is not None
        event_line, data_line, _terminator = frame.split("\n", maxsplit=2)
        assert event_line == f"event: {event_name}"
        assert json.loads(data_line.removeprefix("data: ")) == data


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_name", "legacy_payload", "typed_payload"),
    [
        (
            EVENT_TOOL_RESULT,
            {
                "tool_call_id": "nested-call",
                "parent_tool_call_id": "workflow-call",
                "name": None,
                "result": {"status": "completed"},
            },
            ToolResultEvent(
                tool_call_id="nested-call",
                parent_tool_call_id="workflow-call",
                name=None,
                result={"status": "completed"},
            ),
        ),
        (
            EVENT_WORKFLOW_STATE,
            {
                "tool_call_id": "workflow-call",
                "state": "completed",
                "output_excerpt": "Complete",
            },
            WorkflowStateEvent(
                tool_call_id="workflow-call",
                state="completed",
                output_excerpt="Complete",
            ),
        ),
    ],
)
async def test_typed_payloads_preserve_legacy_sse_wire_bytes(
    event_name: str,
    legacy_payload: dict[str, object],
    typed_payload: StreamEventPayload,
) -> None:
    run_id = UUID("11111111-1111-4111-8111-111111111111")
    conversation_id = UUID("22222222-2222-4222-8222-222222222222")
    typed_sink = StreamSink(run_id=run_id, conversation_id=conversation_id)
    legacy_frame = format_sse_event(
        SinkEvent(
            event=event_name,
            data={
                "run_id": str(run_id),
                "conversation_id": str(conversation_id),
                "seq": 1,
                **legacy_payload,
            },
        )
    )

    await typed_sink.emit(typed_payload)

    assert await typed_sink.next_frame() == legacy_frame
