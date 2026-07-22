# apps/api/integrations/google_ads/tools/__init__.py

"""Google Ads runtime-tool contributions."""

from .list_accounts import DEFINITION as LIST_ACCOUNTS_DEFINITION
from .run_report import DEFINITION as RUN_REPORT_DEFINITION
from .update_campaign_status import DEFINITION as UPDATE_CAMPAIGN_STATUS_DEFINITION

TOOL_DEFINITIONS = (
    LIST_ACCOUNTS_DEFINITION,
    RUN_REPORT_DEFINITION,
    UPDATE_CAMPAIGN_STATUS_DEFINITION,
)

__all__ = ["TOOL_DEFINITIONS"]
