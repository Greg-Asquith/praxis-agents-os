# apps/api/routes/skills/__init__.py

"""Skill route registry."""

from fastapi import APIRouter

from routes.skills.create_skill import router as create_skill_router
from routes.skills.delete_skill import router as delete_skill_router
from routes.skills.get_skill import router as get_skill_router
from routes.skills.list_skills import router as list_skills_router
from routes.skills.update_skill import router as update_skill_router

router = APIRouter(prefix="/skills", tags=["skills"])
router.include_router(list_skills_router)
router.include_router(create_skill_router)
router.include_router(get_skill_router)
router.include_router(update_skill_router)
router.include_router(delete_skill_router)

__all__ = ["router"]
