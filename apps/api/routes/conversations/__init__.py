# apps/api/routes/conversations/__init__.py

"""Conversation route registry."""

from fastapi import APIRouter

from routes.conversations.create_conversation import router as create_conversation_router
from routes.conversations.create_turn import router as create_turn_router
from routes.conversations.delete_conversation import router as delete_conversation_router
from routes.conversations.get_active_run import router as get_active_run_router
from routes.conversations.get_conversation import router as get_conversation_router
from routes.conversations.list_conversations import router as list_conversations_router
from routes.conversations.list_messages import router as list_messages_router
from routes.conversations.mark_read import router as mark_read_router

router = APIRouter(prefix="/conversations", tags=["conversations"])
router.include_router(list_conversations_router)
router.include_router(create_conversation_router)
router.include_router(get_conversation_router)
router.include_router(create_turn_router)
router.include_router(list_messages_router)
router.include_router(get_active_run_router)
router.include_router(mark_read_router)
router.include_router(delete_conversation_router)

__all__ = ["router"]
