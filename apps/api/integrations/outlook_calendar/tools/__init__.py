# apps/api/integrations/outlook_calendar/tools/__init__.py

from .find_meeting_times import DEFINITION as FIND_MEETING_TIMES
from .get_availability import DEFINITION as GET_AVAILABILITY
from .list_events import DEFINITION as LIST_EVENTS
from .read_event import DEFINITION as READ_EVENT
from .search_people import DEFINITION as SEARCH_PEOPLE

TOOL_DEFINITIONS = (
    LIST_EVENTS,
    READ_EVENT,
    GET_AVAILABILITY,
    FIND_MEETING_TIMES,
    SEARCH_PEOPLE,
)
