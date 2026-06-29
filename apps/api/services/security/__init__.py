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
from services.security.queries import (
    count_security_events,
    get_security_event,
    list_security_events,
)

__all__ = [
    "SecurityEventType",
    "count_security_events",
    "get_security_event",
    "list_security_events",
    "safe_record_security_event",
    "safe_record_security_event_committed",
]
