# apps/api/routes/integrations/__init__.py

"""Integration route registry."""

from fastapi import APIRouter

from routes.integrations.clear_context import router as clear_context_router
from routes.integrations.connect_api_key import router as connect_api_key_router
from routes.integrations.connect_service_account import router as connect_service_account_router
from routes.integrations.create_context_group import router as create_context_group_router
from routes.integrations.delete_context_group import router as delete_context_group_router
from routes.integrations.get_connection import router as get_connection_router
from routes.integrations.get_context import router as get_context_router
from routes.integrations.get_preview import router as get_preview_router
from routes.integrations.list_connection_resources import (
    router as list_connection_resources_router,
)
from routes.integrations.list_connections import router as list_connections_router
from routes.integrations.list_context_groups import router as list_context_groups_router
from routes.integrations.list_providers import router as list_providers_router
from routes.integrations.oauth_callback import router as oauth_callback_router
from routes.integrations.receive_event import router as receive_event_router
from routes.integrations.refresh_connection import router as refresh_connection_router
from routes.integrations.rename_connection import router as rename_connection_router
from routes.integrations.revoke_connection import router as revoke_connection_router
from routes.integrations.set_context import router as set_context_router
from routes.integrations.start_oauth_connect import router as start_oauth_connect_router
from routes.integrations.test_connection import router as test_connection_router
from routes.integrations.trigger_discovery import router as trigger_discovery_router
from routes.integrations.update_context_group import router as update_context_group_router
from routes.integrations.update_resource_selection import (
    router as update_resource_selection_router,
)

router = APIRouter(prefix="/integrations", tags=["integrations"])
router.include_router(list_providers_router)
router.include_router(list_connections_router)
router.include_router(get_connection_router)
router.include_router(list_connection_resources_router)
router.include_router(get_preview_router)
router.include_router(get_context_router)
router.include_router(set_context_router)
router.include_router(clear_context_router)
router.include_router(list_context_groups_router)
router.include_router(create_context_group_router)
router.include_router(update_context_group_router)
router.include_router(delete_context_group_router)
router.include_router(start_oauth_connect_router)
router.include_router(oauth_callback_router)
router.include_router(connect_api_key_router)
router.include_router(connect_service_account_router)
router.include_router(rename_connection_router)
router.include_router(test_connection_router)
router.include_router(refresh_connection_router)
router.include_router(receive_event_router)
router.include_router(revoke_connection_router)
router.include_router(update_resource_selection_router)
router.include_router(trigger_discovery_router)

__all__ = ["router"]
