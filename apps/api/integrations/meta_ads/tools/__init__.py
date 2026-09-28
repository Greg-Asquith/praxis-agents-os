# apps/api/integrations/meta_ads/tools/__init__.py

"""Meta Ads tool contributions."""

from .get_accounts import DEFINITION as GET_ACCOUNTS
from .list_activities import DEFINITION as LIST_ACTIVITIES
from .list_custom_conversions import DEFINITION as LIST_CUSTOM_CONVERSIONS
from .list_objects import DEFINITION as LIST_OBJECTS
from .run_insights import DEFINITION as RUN_INSIGHTS

TOOL_DEFINITIONS = (
    RUN_INSIGHTS,
    GET_ACCOUNTS,
    LIST_OBJECTS,
    LIST_CUSTOM_CONVERSIONS,
    LIST_ACTIVITIES,
)
