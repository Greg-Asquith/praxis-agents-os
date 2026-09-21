# apps/api/services/integrations/write_lifecycle.py

"""Prepares audited writes and delegates provider-specific terminal evidence."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from services.audit_events import PendingIntegrationOperationDetail
from services.integrations.operations import IntegrationAuditOutcome


@dataclass(frozen=True)
class PreparedIntegrationWrite:
    pending: PendingIntegrationOperationDetail
    mutate: Callable[[], Awaitable[None]]


@dataclass
class IntegrationWriteCallbacks:
    prepare_operation: Callable[[], Awaitable[PreparedIntegrationWrite]]
    successful: Callable[[PendingIntegrationOperationDetail], IntegrationAuditOutcome[dict]]
    failed: Callable[[PendingIntegrationOperationDetail, Exception], IntegrationAuditOutcome[dict]]
    cancelled: Callable[[asyncio.CancelledError, PendingIntegrationOperationDetail], None]
    _prepared: PreparedIntegrationWrite | None = field(default=None, init=False)

    async def prepare(self) -> PendingIntegrationOperationDetail:
        self._prepared = await self.prepare_operation()
        return self._prepared.pending

    async def execute(self) -> IntegrationAuditOutcome[dict]:
        prepared = self._prepared
        if prepared is None:
            raise RuntimeError("Integration write preparation did not complete.")
        # The audit runner persists pending intent before invoking this callback.
        try:
            await prepared.mutate()
        except asyncio.CancelledError as exc:
            self.cancelled(exc, prepared.pending)
            raise
        except Exception as exc:
            return self.failed(prepared.pending, exc)
        return self.successful(prepared.pending)
