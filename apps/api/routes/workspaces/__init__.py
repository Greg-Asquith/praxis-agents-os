# apps/api/routes/workspaces/__init__.py

"""Workspace route registry."""

from fastapi import APIRouter

from routes.workspaces.create_workspace import router as create_workspace_router
from routes.workspaces.delete_workspace import router as delete_workspace_router
from routes.workspaces.get_workspace import router as get_workspace_router
from routes.workspaces.invitations import router as invitations_router
from routes.workspaces.list_workspaces import router as list_workspaces_router
from routes.workspaces.memberships import router as memberships_router
from routes.workspaces.update_workspace import router as update_workspace_router

router = APIRouter(prefix="/workspaces", tags=["workspaces"])
router.include_router(list_workspaces_router)
router.include_router(create_workspace_router)
router.include_router(invitations_router)
router.include_router(memberships_router)
router.include_router(get_workspace_router)
router.include_router(update_workspace_router)
router.include_router(delete_workspace_router)

__all__ = ["router"]
