"""Agent-memory model factories for tests."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from models.agent_memories import AgentMemory


def build_memory(
    *,
    workspace_id: UUID,
    scope: str = "workspace",
    agent_id: UUID | None = None,
    user_id: UUID | None = None,
    kind: str = "note",
    memory_type: str = "fact",
    title: str = "Remembered fact",
    content_md: str = "A durable fact.",
    source: str = "interactive",
    created_by: str = "agent",
    created_by_user_id: UUID | None = None,
    **overrides: object,
) -> AgentMemory:
    """Build an unsaved memory row with a valid scope tuple."""
    values: dict[str, object] = {
        "id": uuid4(),
        "workspace_id": workspace_id,
        "scope": scope,
        "agent_id": agent_id if scope == "agent" else None,
        "user_id": user_id if scope == "user" else None,
        "kind": kind,
        "memory_type": memory_type,
        "title": title,
        "content_md": content_md,
        "importance": 3,
        "confidence": 0.8,
        "reinforcement_count": 0,
        "access_count": 0,
        "status": "active",
        "source": source,
        "created_by": created_by,
        "created_by_user_id": created_by_user_id,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    values.update(overrides)
    return AgentMemory(**values)
