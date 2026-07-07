# apps/api/services/security/__init__.py

"""Security event services.

Writes go through :func:`safe_record_security_event` so a failed security-log
write never rolls back the request being protected.
"""

from services.security.enums import SecurityEventType
from services.security.events import (
    safe_record_security_event,
    safe_record_security_event_committed,
)
from services.security.get_event import get_security_event_for_super_admin
from services.security.list_events import list_security_events_for_super_admin
from services.security.queries import (
    get_security_event,
    list_security_events,
    list_security_events_page,
)

__all__ = [
    "SecurityEventType",
    "get_security_event",
    "get_security_event_for_super_admin",
    "list_security_events",
    "list_security_events_for_super_admin",
    "list_security_events_page",
    "safe_record_security_event",
    "safe_record_security_event_committed",
]
