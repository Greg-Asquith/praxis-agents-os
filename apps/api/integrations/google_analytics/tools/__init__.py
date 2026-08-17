# apps/api/integrations/google_analytics/tools/__init__.py

"""Google Analytics runtime-tool contributions."""

from .list_report_fields import DEFINITION as LIST_REPORT_FIELDS_DEFINITION
from .run_report import DEFINITION as RUN_REPORT_DEFINITION

TOOL_DEFINITIONS = (LIST_REPORT_FIELDS_DEFINITION, RUN_REPORT_DEFINITION)

__all__ = ["TOOL_DEFINITIONS"]
