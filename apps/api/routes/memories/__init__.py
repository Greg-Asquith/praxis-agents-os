# apps/api/routes/memories/__init__.py

"""Memory-management route registry."""

from fastapi import APIRouter

from routes.memories.delete_memory import router as delete_memory_router
from routes.memories.get_memory import router as get_memory_router
from routes.memories.list_memories import router as list_memories_router
from routes.memories.update_memory import router as update_memory_router

router = APIRouter(prefix="/memories", tags=["memories"])
router.include_router(list_memories_router)
router.include_router(get_memory_router)
router.include_router(update_memory_router)
router.include_router(delete_memory_router)

__all__ = ["router"]
