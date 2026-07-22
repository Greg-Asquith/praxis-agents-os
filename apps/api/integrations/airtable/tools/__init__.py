# apps/api/integrations/airtable/tools/__init__.py

"""Airtable runtime-tool contributions."""

from .create_record import DEFINITION as CREATE_RECORD_DEFINITION
from .get_record import DEFINITION as GET_RECORD_DEFINITION
from .list_records import DEFINITION as LIST_RECORDS_DEFINITION
from .update_record import DEFINITION as UPDATE_RECORD_DEFINITION

TOOL_DEFINITIONS = (
    LIST_RECORDS_DEFINITION,
    GET_RECORD_DEFINITION,
    CREATE_RECORD_DEFINITION,
    UPDATE_RECORD_DEFINITION,
)

__all__ = ["TOOL_DEFINITIONS"]
