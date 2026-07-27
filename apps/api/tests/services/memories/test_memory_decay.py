"""Pure confidence-decay behavior."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from services.memories.utils import effective_confidence
from tests.factories.memories import build_memory


def _memory(*, memory_type: str = "fact", kind: str = "note"):
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    return build_memory(
        workspace_id=uuid4(),
        memory_type=memory_type,
        kind=kind,
        confidence=0.8,
        created_at=created_at,
        updated_at=created_at,
    )


def test_decay_rates_have_expected_order() -> None:
    now = datetime(2026, 2, 1, tzinfo=UTC)
    values = {
        memory_type: effective_confidence(_memory(memory_type=memory_type), now=now)
        for memory_type in ("episode", "outcome", "fact", "preference")
    }
    assert values["episode"] < values["outcome"] < values["fact"] < values["preference"]


def test_decay_is_floored() -> None:
    memory = _memory(memory_type="episode")
    assert effective_confidence(
        memory,
        now=memory.created_at + timedelta(days=10_000),
    ) == pytest.approx(0.05)


def test_last_reinforcement_resets_decay_clock() -> None:
    memory = _memory()
    now = memory.created_at + timedelta(days=30)
    before = effective_confidence(memory, now=now)
    memory.last_reinforced_at = now
    assert effective_confidence(memory, now=now) == pytest.approx(0.8)
    assert effective_confidence(memory, now=now) > before


def test_new_memory_has_unchanged_confidence() -> None:
    memory = _memory()
    assert effective_confidence(memory, now=memory.created_at) == pytest.approx(0.8)


def test_core_memory_does_not_decay() -> None:
    memory = _memory(kind="core", memory_type="episode")
    assert effective_confidence(
        memory,
        now=memory.created_at + timedelta(days=10_000),
    ) == pytest.approx(0.8)
