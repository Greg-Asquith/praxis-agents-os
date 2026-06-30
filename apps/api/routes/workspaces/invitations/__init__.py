# apps/api/routes/workspaces/invitations/__init__.py

"""Workspace invitation route registry."""

from fastapi import APIRouter

from routes.workspaces.invitations.accept_invitation_by_id import (
    router as accept_invitation_by_id_router,
)
from routes.workspaces.invitations.accept_invitation_by_token import (
    router as accept_invitation_by_token_router,
)
from routes.workspaces.invitations.create_invitation import router as create_invitation_router
from routes.workspaces.invitations.delete_invitation import router as delete_invitation_router
from routes.workspaces.invitations.get_invitation import router as get_invitation_router
from routes.workspaces.invitations.list_invitations import router as list_invitations_router
from routes.workspaces.invitations.update_invitation import router as update_invitation_router

router = APIRouter()
router.include_router(accept_invitation_by_token_router)
router.include_router(accept_invitation_by_id_router)
router.include_router(list_invitations_router)
router.include_router(create_invitation_router)
router.include_router(get_invitation_router)
router.include_router(update_invitation_router)
router.include_router(delete_invitation_router)

__all__ = ["router"]
