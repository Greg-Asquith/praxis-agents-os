"""Tests for generic job concurrency diagnostics."""

from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.jobs import Job
from services.jobs.log_concurrency_warnings import log_job_concurrency_warnings
from tests.factories import build_job, build_workspace

pytestmark = pytest.mark.asyncio


async def test_logs_workspace_concurrency_warning(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await db_session.execute(delete(Job))
    await db_session.flush()
    monkeypatch.setattr(settings, "JOBS_WORKSPACE_CONCURRENCY_LIMIT", 1)
    warnings: list[str] = []

    def record_warning(message: str, *args: object, **kwargs: object) -> None:
        warnings.append(message)

    monkeypatch.setattr(
        "services.jobs.log_concurrency_warnings.logger.warning",
        record_warning,
    )
    workspace = build_workspace(slug=f"job-limit-{uuid4().hex[:8]}")
    db_session.add(workspace)
    await db_session.flush()
    db_session.add_all(
        [
            build_job(workspace_id=workspace.id, payload={"n": 1}),
            build_job(workspace_id=workspace.id, payload={"n": 2}),
        ]
    )
    await db_session.flush()

    await log_job_concurrency_warnings(db_session)

    assert any("exceeds configured warning threshold" in message for message in warnings)
