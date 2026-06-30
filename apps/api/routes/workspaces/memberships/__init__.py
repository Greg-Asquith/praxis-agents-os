# apps/api/routes/workspaces/memberships/__init__.py

"""Workspace membership route registry."""

from fastapi import APIRouter

from routes.workspaces.memberships.create_membership import router as create_membership_router
from routes.workspaces.memberships.delete_membership import router as delete_membership_router
from routes.workspaces.memberships.get_membership import router as get_membership_router
from routes.workspaces.memberships.list_memberships import router as list_memberships_router
from routes.workspaces.memberships.update_membership import router as update_membership_router

router = APIRouter()
router.include_router(list_memberships_router)
router.include_router(create_membership_router)
router.include_router(get_membership_router)
router.include_router(update_membership_router)
router.include_router(delete_membership_router)

__all__ = ["router"]
