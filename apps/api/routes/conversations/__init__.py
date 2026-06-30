# apps/api/routes/conversations/__init__.py

"""Conversation route registry."""

from fastapi import APIRouter

from routes.conversations.create_turn import router as create_turn_router
from routes.conversations.get_active_run import router as get_active_run_router
from routes.conversations.list_messages import router as list_messages_router

router = APIRouter(prefix="/conversations", tags=["conversations"])
router.include_router(create_turn_router)
router.include_router(list_messages_router)
router.include_router(get_active_run_router)

__all__ = ["router"]
