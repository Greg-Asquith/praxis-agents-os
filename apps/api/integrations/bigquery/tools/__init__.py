# apps/api/integrations/bigquery/tools/__init__.py

"""BigQuery runtime tool contributions."""

from .get_table_schema import DEFINITION as GET_TABLE_SCHEMA
from .list_tables import DEFINITION as LIST_TABLES
from .run_query import DEFINITION as RUN_QUERY

TOOL_DEFINITIONS = (LIST_TABLES, GET_TABLE_SCHEMA, RUN_QUERY)

__all__ = ["TOOL_DEFINITIONS"]
