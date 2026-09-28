# apps/api/tests/contract/test_stream_protocol.py

"""Drift and wire-compatibility checks for the agent stream protocol."""

import json
from pathlib import Path
from uuid import UUID

import pytest

from services.agents.runtime.sinks import StreamSink
from services.agents.runtime.stream_protocol import (
    STREAM_EVENT_MODELS,
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
