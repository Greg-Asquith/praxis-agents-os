# apps/api/tests/services/ai_usage/test_domain.py

"""AI usage event validation and purpose table tests."""

from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.database import get_maintenance_async_db_session_factory
from models.ai_usage_event import AIUsageEvent
from models.ai_usage_purpose import AIUsagePurpose
from services.ai_usage.domain import AI_USAGE_PURPOSES, AIUsageEventData
from tests.factories import build_workspace


def _event(**overrides) -> AIUsageEventData:
    values = {
        "workspace_id": uuid4(),
        "provider": "openai",
        "model": "gpt-5.6-luna",
        "purpose": "agent_run",
    }
    values.update(overrides)
    return AIUsageEventData(**values)


@pytest.mark.parametrize(
    "overrides",
    [
        {"purpose": " "},
        {"input_tokens": -1},
    ],
)
def test_invalid_event_values_fail_closed(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _event(**overrides)


def test_details_must_be_json_serializable_and_bounded() -> None:
    with pytest.raises(ValueError, match="JSON serializable"):
        _event(details={"bad": object()})

    with pytest.raises(ValueError, match="4096-byte"):
        _event(details={"value": "x" * 4097})


async def test_core_purposes_are_seeded_and_unknown_purposes_are_refused(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with get_maintenance_async_db_session_factory()() as db:
        seeded = set(await db.scalars(sa.select(AIUsagePurpose.key)))
        assert set(AI_USAGE_PURPOSES) <= seeded

        workspace = build_workspace(slug=f"purposes-{uuid4().hex[:8]}")
        db.add(workspace)
        await db.flush()
        db.add(
            AIUsageEvent(
                workspace_id=workspace.id,
                provider="openai",
                model="gpt-5.6-luna",
                purpose="not_a_purpose",
            )
        )
        with pytest.raises(IntegrityError, match="ai_usage_events_purpose_fkey"):
            await db.flush()
