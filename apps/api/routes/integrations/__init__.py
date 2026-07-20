# apps/api/routes/integrations/__init__.py

"""Integration route registry."""

from fastapi import APIRouter

from routes.integrations.connect_api_key import router as connect_api_key_router
from routes.integrations.get_connection import router as get_connection_router
from routes.integrations.list_connection_resources import (
    router as list_connection_resources_router,
)
from routes.integrations.list_connections import router as list_connections_router
from routes.integrations.list_providers import router as list_providers_router
from routes.integrations.oauth_callback import router as oauth_callback_router
from routes.integrations.refresh_connection import router as refresh_connection_router
from routes.integrations.rename_connection import router as rename_connection_router
from routes.integrations.revoke_connection import router as revoke_connection_router
from routes.integrations.start_oauth_connect import router as start_oauth_connect_router
from routes.integrations.test_connection import router as test_connection_router
from routes.integrations.trigger_discovery import router as trigger_discovery_router
from routes.integrations.update_resource_selection import (
    router as update_resource_selection_router,
)

router = APIRouter(prefix="/integrations", tags=["integrations"])
router.include_router(list_providers_router)
router.include_router(list_connections_router)
router.include_router(get_connection_router)
router.include_router(list_connection_resources_router)
router.include_router(start_oauth_connect_router)
router.include_router(oauth_callback_router)
router.include_router(connect_api_key_router)
router.include_router(rename_connection_router)
router.include_router(test_connection_router)
router.include_router(refresh_connection_router)
router.include_router(revoke_connection_router)
router.include_router(update_resource_selection_router)
router.include_router(trigger_discovery_router)

__all__ = ["router"]
