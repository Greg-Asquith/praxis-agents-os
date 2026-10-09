# apps/api/integrations/meta_ads/tools/__init__.py

"""Meta Ads tool contributions."""

from .create_ads import DEFINITION as CREATE_ADS
from .get_accounts import DEFINITION as GET_ACCOUNTS
from .list_activities import DEFINITION as LIST_ACTIVITIES
from .list_assets import DEFINITION as LIST_ASSETS
from .list_conversions import DEFINITION as LIST_CONVERSIONS
from .list_objects import DEFINITION as LIST_OBJECTS
from .run_insights import DEFINITION as RUN_INSIGHTS
from .update_budgets import DEFINITION as UPDATE_BUDGETS
from .update_status import DEFINITION as UPDATE_STATUS
from .upload_media import DEFINITION as UPLOAD_MEDIA

TOOL_DEFINITIONS = (
    RUN_INSIGHTS,
    GET_ACCOUNTS,
    LIST_OBJECTS,
    LIST_CONVERSIONS,
    LIST_ACTIVITIES,
    LIST_ASSETS,
    UPDATE_STATUS,
    UPDATE_BUDGETS,
    UPLOAD_MEDIA,
    CREATE_ADS,
)
