# apps/api/routes/auth/__init__.py

"""Auth route registry."""

from fastapi import APIRouter

from routes.auth.get_identities import router as get_identities_router
from routes.auth.get_me import router as get_me_router
from routes.auth.login import router as login_router
from routes.auth.logout import router as logout_router
from routes.auth.oauth.complete_oauth_login import router as complete_oauth_login_router
from routes.auth.oauth.create_oauth_authorization_url import (
    router as create_oauth_authorization_url_router,
)
from routes.auth.oauth.list_oauth_providers import router as list_oauth_providers_router
from routes.auth.password.change_password import router as change_password_router
from routes.auth.register import router as register_router
from routes.auth.sessions.list_sessions import router as list_sessions_router
from routes.auth.sessions.refresh_session import router as refresh_session_router
from routes.auth.sessions.revoke_session import router as revoke_session_router
from routes.auth.sessions.revoke_sessions import router as revoke_sessions_router
from routes.auth.totp.disable_totp import router as disable_totp_router
from routes.auth.totp.enable_totp import router as enable_totp_router
from routes.auth.totp.setup_totp import router as setup_totp_router
from routes.auth.totp.verify_totp import router as verify_totp_router
from routes.auth.update_me import router as update_me_router

router = APIRouter(prefix="/auth", tags=["auth"])
router.include_router(list_oauth_providers_router)
router.include_router(register_router)
router.include_router(login_router)
router.include_router(logout_router)
router.include_router(get_me_router)
router.include_router(get_identities_router)
router.include_router(update_me_router)
router.include_router(refresh_session_router)
router.include_router(list_sessions_router)
router.include_router(revoke_sessions_router)
router.include_router(revoke_session_router)
router.include_router(change_password_router)
router.include_router(create_oauth_authorization_url_router)
router.include_router(complete_oauth_login_router)
router.include_router(setup_totp_router)
router.include_router(enable_totp_router)
router.include_router(verify_totp_router)
router.include_router(disable_totp_router)

__all__ = ["router"]
