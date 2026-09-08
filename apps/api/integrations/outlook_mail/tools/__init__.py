# apps/api/integrations/outlook_mail/tools/__init__.py

from .create_draft import DEFINITION as CREATE_DRAFT
from .forward_message import DEFINITION as FORWARD_MESSAGE
from .list_mail_folders import DEFINITION as LIST_FOLDERS
from .move_message import DEFINITION as MOVE_MESSAGE
from .read_attachment import DEFINITION as READ_ATTACHMENT
from .read_message import DEFINITION as READ_MESSAGE
from .reply_to_message import DEFINITION as REPLY_TO_MESSAGE
from .search_messages import DEFINITION as SEARCH_MESSAGES
from .search_people import DEFINITION as SEARCH_PEOPLE
from .send_draft import DEFINITION as SEND_DRAFT
from .send_message import DEFINITION as SEND_MESSAGE
from .update_message import DEFINITION as UPDATE_MESSAGE

TOOL_DEFINITIONS = (
    SEARCH_MESSAGES,
    READ_MESSAGE,
    LIST_FOLDERS,
    READ_ATTACHMENT,
    SEARCH_PEOPLE,
    SEND_MESSAGE,
    SEND_DRAFT,
    REPLY_TO_MESSAGE,
    FORWARD_MESSAGE,
    CREATE_DRAFT,
    MOVE_MESSAGE,
    UPDATE_MESSAGE,
)
