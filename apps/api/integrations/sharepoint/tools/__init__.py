# apps/api/integrations/sharepoint/tools/__init__.py

"""SharePoint tool definitions."""

from .list_folder import DEFINITION as LIST_FOLDER
from .open_link import DEFINITION as OPEN_LINK
from .read_file import DEFINITION as READ_FILE
from .search_files import DEFINITION as SEARCH_FILES

TOOL_DEFINITIONS = (LIST_FOLDER, SEARCH_FILES, READ_FILE, OPEN_LINK)
