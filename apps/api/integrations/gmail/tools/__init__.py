# apps/api/integrations/gmail/tools/__init__.py

"""Gmail runtime-tool contributions."""

from .read_message import DEFINITION as READ_MESSAGE_DEFINITION
from .search_messages import DEFINITION as SEARCH_MESSAGES_DEFINITION
from .send_message import DEFINITION as SEND_MESSAGE_DEFINITION

TOOL_DEFINITIONS = (
    SEARCH_MESSAGES_DEFINITION,
    READ_MESSAGE_DEFINITION,
    SEND_MESSAGE_DEFINITION,
)

__all__ = ["TOOL_DEFINITIONS"]
