# apps/api/integrations/google_analytics/tools/__init__.py

"""Google Analytics runtime-tool contributions."""

from .check_report_fields import DEFINITION as CHECK_REPORT_FIELDS_DEFINITION
from .list_report_fields import DEFINITION as LIST_REPORT_FIELDS_DEFINITION
from .run_realtime_report import DEFINITION as RUN_REALTIME_REPORT_DEFINITION
from .run_report import DEFINITION as RUN_REPORT_DEFINITION

TOOL_DEFINITIONS = (
    CHECK_REPORT_FIELDS_DEFINITION,
    LIST_REPORT_FIELDS_DEFINITION,
    RUN_REALTIME_REPORT_DEFINITION,
    RUN_REPORT_DEFINITION,
)

__all__ = ["TOOL_DEFINITIONS"]
