# apps/api/services/agents/runtime/sinks.py

"""Runtime event sinks for tests, SSE routes, and scheduled execution."""

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from pydantic_core import to_jsonable_python


@dataclass(frozen=True)
class SinkEvent:
    """One sequenced runtime event emitted by an agent run."""

    event: str
    data: dict[str, Any]


class EventSink(Protocol):
    """Receives normalized runtime events from ``execute_run``."""

    async def emit(self, event: str, payload: Mapping[str, Any] | None = None) -> None:
        """Emit one event."""

    async def close(self) -> None:
        """Mark the sink complete."""


class SequencedSink:
    """Base sink that owns the run/conversation envelope and sequence numbers."""

    def __init__(self, *, run_id: UUID, conversation_id: UUID):
        self.run_id = run_id
        self.conversation_id = conversation_id
        self._seq = 0

    def _event(self, event: str, payload: Mapping[str, Any] | None = None) -> SinkEvent:
        self._seq += 1
        data = {
            "run_id": str(self.run_id),
            "conversation_id": str(self.conversation_id),
            "seq": self._seq,
        }
        data.update(to_jsonable_python(dict(payload or {})))
        return SinkEvent(event=event, data=data)


class NullSink(SequencedSink):
    """Sink for scheduled/background runs where no live client is listening."""

    async def emit(self, event: str, payload: Mapping[str, Any] | None = None) -> None:
        self._event(event, payload)

    async def close(self) -> None:
        return None


class CollectingSink(SequencedSink):
    """In-memory sink used by runtime tests."""

    def __init__(self, *, run_id: UUID, conversation_id: UUID):
        super().__init__(run_id=run_id, conversation_id=conversation_id)
        self.events: list[SinkEvent] = []

    async def emit(self, event: str, payload: Mapping[str, Any] | None = None) -> None:
        self.events.append(self._event(event, payload))

    async def close(self) -> None:
        return None


class StreamSink(SequencedSink):
    """Async queue sink that yields formatted SSE frames."""

    def __init__(self, *, run_id: UUID, conversation_id: UUID, max_queue_size: int = 0):
        super().__init__(run_id=run_id, conversation_id=conversation_id)
        self._queue: asyncio.Queue[SinkEvent | None] = asyncio.Queue(maxsize=max_queue_size)
        self._closed = False
        self._detached = False

    async def emit(self, event: str, payload: Mapping[str, Any] | None = None) -> None:
        if self._closed or self._detached:
            return
        try:
            self._queue.put_nowait(self._event(event, payload))
        except asyncio.QueueFull:
            self.detach()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if not self._detached:
            try:
                self._queue.put_nowait(None)
            except asyncio.QueueFull:
                self.detach()

    def detach(self) -> None:
        """Stop queueing events after the live HTTP client has gone away."""
        self._detached = True

    @property
    def detached(self) -> bool:
        return self._detached

    async def next_frame(self) -> str | None:
        """Wait for and format the next SSE frame, or return None when closed."""
        event = await self._queue.get()
        if event is None:
            return None
        return format_sse_event(event)

    async def __aiter__(self) -> AsyncIterator[str]:
        while True:
            frame = await self.next_frame()
            if frame is None:
                break
            yield frame


def format_sse_event(event: SinkEvent) -> str:
    """Serialize one event as an SSE frame."""
    data = json.dumps(event.data, separators=(",", ":"))
    return f"event: {event.event}\ndata: {data}\n\n"
