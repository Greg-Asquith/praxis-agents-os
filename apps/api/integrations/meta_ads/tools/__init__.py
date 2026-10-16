# apps/api/integrations/meta_ads/tools/__init__.py

"""Meta Ads tool contributions."""

from .copy_ads import DEFINITION as COPY_ADS
from .create_ad_set import DEFINITION as CREATE_AD_SET
from .create_ads import DEFINITION as CREATE_ADS
from .create_campaign import DEFINITION as CREATE_CAMPAIGN
from .estimate_audience import DEFINITION as ESTIMATE_AUDIENCE
from .get_accounts import DEFINITION as GET_ACCOUNTS
from .launch_campaign import DEFINITION as LAUNCH_CAMPAIGN
from .list_activities import DEFINITION as LIST_ACTIVITIES
from .list_assets import DEFINITION as LIST_ASSETS
from .list_conversions import DEFINITION as LIST_CONVERSIONS
from .list_objects import DEFINITION as LIST_OBJECTS
from .run_insights import DEFINITION as RUN_INSIGHTS
from .search_targeting import DEFINITION as SEARCH_TARGETING
from .update_ad_sets import DEFINITION as UPDATE_AD_SETS
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
    SEARCH_TARGETING,
    ESTIMATE_AUDIENCE,
    UPDATE_STATUS,
    UPDATE_BUDGETS,
    UPDATE_AD_SETS,
    UPLOAD_MEDIA,
    CREATE_CAMPAIGN,
    CREATE_AD_SET,
    CREATE_ADS,
    COPY_ADS,
    LAUNCH_CAMPAIGN,
)
