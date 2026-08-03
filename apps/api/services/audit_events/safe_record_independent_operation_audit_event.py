# apps/api/services/audit_events/safe_record_independent_operation_audit_event.py

"""Independently committed audit writes for operations that fail."""

import logging
from typing import Any
from uuid import UUID

from core.database import (
    configure_async_db_session,
    get_async_db_session_factory,
    get_maintenance_async_db_session_factory,
    set_session_tenant_context,
)
from services.audit_events.operations import safe_record_operation_audit_event

logger = logging.getLogger(__name__)


async def safe_record_independent_operation_audit_event(**kwargs: Any) -> None:
    """Commit an audit event independently of a caller transaction.

    Use this only for failed operations whose caller transaction is expected to
    roll back. Routine success audits should remain atomic with their operation.
    """
    try:
        workspace_id = _uuid_or_none(kwargs.get("workspace_id"))
        actor_user_id = _uuid_or_none(kwargs.get("actor_id"))
        session_factory = (
            get_async_db_session_factory()
            if workspace_id is not None
            else get_maintenance_async_db_session_factory()
        )
        async with session_factory() as audit_db:
            await configure_async_db_session(audit_db)
            if workspace_id is not None:
                await set_session_tenant_context(
                    audit_db,
                    workspace_id=workspace_id,
                    user_id=actor_user_id,
                )
            await safe_record_operation_audit_event(audit_db, **kwargs)
            await audit_db.commit()
    except Exception:
        logger.error("Failed to commit independent audit event", exc_info=True)


def _uuid_or_none(value: object) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None
