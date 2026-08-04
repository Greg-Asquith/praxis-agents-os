"""Workspace bucket provisioning job tests."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from services.jobs.handlers import provision_workspace_bucket as handler_module
from tests.factories import build_job

pytestmark = pytest.mark.asyncio


async def test_provision_workspace_bucket_job_delegates_idempotently(monkeypatch) -> None:
    workspace_id = uuid4()
    provider = AsyncMock()
    monkeypatch.setattr(handler_module, "get_storage_provider", lambda: provider)
    job = build_job(
        kind="storage.provision_workspace_bucket",
        workspace_id=workspace_id,
        payload={"workspace_id": str(workspace_id)},
    )

    await handler_module.provision_workspace_bucket(AsyncMock(), job)
    await handler_module.provision_workspace_bucket(AsyncMock(), job)

    assert provider.ensure_workspace_bucket.await_count == 2
    provider.ensure_workspace_bucket.assert_awaited_with(workspace_id)


async def test_provision_workspace_bucket_job_requires_workspace_owner() -> None:
    job = build_job(kind="storage.provision_workspace_bucket")

    with pytest.raises(RuntimeError, match="workspace-owned job"):
        await handler_module.provision_workspace_bucket(AsyncMock(), job)
