# apps/api/integrations/sharepoint/tools/__init__.py

"""SharePoint tool definitions."""

from .create_folder import DEFINITION as CREATE_FOLDER
from .find_in_file import DEFINITION as FIND_IN_FILE
from .list_folder import DEFINITION as LIST_FOLDER
from .open_link import DEFINITION as OPEN_LINK
from .read_file import DEFINITION as READ_FILE
from .search_files import DEFINITION as SEARCH_FILES
from .update_file import DEFINITION as UPDATE_FILE
from .write_file import DEFINITION as WRITE_FILE

TOOL_DEFINITIONS = (
    LIST_FOLDER,
    SEARCH_FILES,
    READ_FILE,
    FIND_IN_FILE,
    CREATE_FOLDER,
    WRITE_FILE,
    UPDATE_FILE,
    OPEN_LINK,
)
