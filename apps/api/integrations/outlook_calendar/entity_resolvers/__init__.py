# apps/api/integrations/outlook_calendar/entity_resolvers/__init__.py

from .calendar import OUTLOOK_CALENDAR_RESOLVER
from .event import OUTLOOK_EVENT_RESOLVER

__all__ = ["OUTLOOK_CALENDAR_RESOLVER", "OUTLOOK_EVENT_RESOLVER"]
