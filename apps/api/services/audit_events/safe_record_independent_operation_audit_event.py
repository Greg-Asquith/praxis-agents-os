"""Independently committed audit writes for operations that fail."""

import logging
from typing import Any

from core.database import configure_async_db_session, get_async_db_session_factory
from services.audit_events.operations import safe_record_operation_audit_event

logger = logging.getLogger(__name__)


async def safe_record_independent_operation_audit_event(**kwargs: Any) -> None:
    """Commit an audit event independently of a caller transaction.

    Use this only for failed operations whose caller transaction is expected to
    roll back. Routine success audits should remain atomic with their operation.
    """
    try:
        session_factory = get_async_db_session_factory()
        async with session_factory() as audit_db:
            await configure_async_db_session(audit_db)
            await safe_record_operation_audit_event(audit_db, **kwargs)
            await audit_db.commit()
    except Exception:
        logger.error("Failed to commit independent audit event", exc_info=True)
