# apps/api/integrations/outlook_calendar/tools/__init__.py

from .cancel_event import DEFINITION as CANCEL_EVENT
from .create_event import DEFINITION as CREATE_EVENT
from .find_meeting_times import DEFINITION as FIND_MEETING_TIMES
from .get_availability import DEFINITION as GET_AVAILABILITY
from .list_events import DEFINITION as LIST_EVENTS
from .read_event import DEFINITION as READ_EVENT
from .respond_to_event import DEFINITION as RESPOND_TO_EVENT
from .search_people import DEFINITION as SEARCH_PEOPLE
from .update_event import DEFINITION as UPDATE_EVENT

TOOL_DEFINITIONS = (
    LIST_EVENTS,
    READ_EVENT,
    GET_AVAILABILITY,
    FIND_MEETING_TIMES,
    SEARCH_PEOPLE,
    CREATE_EVENT,
    UPDATE_EVENT,
    RESPOND_TO_EVENT,
    CANCEL_EVENT,
)
