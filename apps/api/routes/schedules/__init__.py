# apps/api/routes/schedules/__init__.py

"""Schedule route registry."""

from fastapi import APIRouter

from routes.schedules.create_schedule import router as create_schedule_router
from routes.schedules.delete_schedule import router as delete_schedule_router
from routes.schedules.enable_schedule import router as enable_schedule_router
from routes.schedules.get_schedule import router as get_schedule_router
from routes.schedules.list_schedule_runs import router as list_schedule_runs_router
from routes.schedules.list_schedules import router as list_schedules_router
from routes.schedules.pause_schedule import router as pause_schedule_router
from routes.schedules.preview_schedule import router as preview_schedule_router
from routes.schedules.run_schedule_now import router as run_schedule_now_router
from routes.schedules.update_schedule import router as update_schedule_router

router = APIRouter(prefix="/schedules", tags=["schedules"])
router.include_router(list_schedules_router)
router.include_router(create_schedule_router)
router.include_router(preview_schedule_router)
router.include_router(get_schedule_router)
router.include_router(update_schedule_router)
router.include_router(delete_schedule_router)
router.include_router(pause_schedule_router)
router.include_router(enable_schedule_router)
router.include_router(run_schedule_now_router)
router.include_router(list_schedule_runs_router)

__all__ = ["router"]
