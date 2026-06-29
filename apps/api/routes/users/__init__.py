# apps/api/routes/users/__init__.py

"""User-management route registry."""

from fastapi import APIRouter

from routes.users.create_user import router as create_user_router
from routes.users.delete_user import router as delete_user_router
from routes.users.get_user import router as get_user_router
from routes.users.list_users import router as list_users_router
from routes.users.set_user_password import router as set_user_password_router
from routes.users.update_user import router as update_user_router

router = APIRouter(prefix="/users", tags=["users"])
router.include_router(list_users_router)
router.include_router(create_user_router)
router.include_router(get_user_router)
router.include_router(update_user_router)
router.include_router(set_user_password_router)
router.include_router(delete_user_router)

__all__ = ["router"]
