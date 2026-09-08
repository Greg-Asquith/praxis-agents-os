# apps/api/integrations/outlook_mail/tools/__init__.py

from .list_mail_folders import DEFINITION as LIST_FOLDERS
from .read_attachment import DEFINITION as READ_ATTACHMENT
from .read_message import DEFINITION as READ_MESSAGE
from .search_messages import DEFINITION as SEARCH_MESSAGES
from .search_people import DEFINITION as SEARCH_PEOPLE

TOOL_DEFINITIONS = (SEARCH_MESSAGES, READ_MESSAGE, LIST_FOLDERS, READ_ATTACHMENT, SEARCH_PEOPLE)
