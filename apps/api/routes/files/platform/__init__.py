# apps/api/routes/files/platform/__init__.py

"""Platform file management route registry."""

from fastapi import APIRouter

from routes.files.platform.confirm_file_upload import router as confirm_file_upload_router
from routes.files.platform.create_file_upload import router as create_file_upload_router
from routes.files.platform.delete_file import router as delete_file_router
from routes.files.platform.get_file import router as get_file_router
from routes.files.platform.get_file_content import router as get_file_content_router
from routes.files.platform.get_file_preview import router as get_file_preview_router
from routes.files.platform.list_file_revisions import router as list_file_revisions_router
from routes.files.platform.list_files import router as list_files_router
from routes.files.platform.publish_file import router as publish_file_router
from routes.files.platform.restore_file_revision import router as restore_file_revision_router
from routes.files.platform.update_file import router as update_file_router
from routes.files.platform.withdraw_file import router as withdraw_file_router

router = APIRouter(prefix="/platform")
router.include_router(confirm_file_upload_router)
router.include_router(create_file_upload_router)
router.include_router(delete_file_router)
router.include_router(get_file_router)
router.include_router(get_file_content_router)
router.include_router(get_file_preview_router)
router.include_router(list_file_revisions_router)
router.include_router(list_files_router)
router.include_router(publish_file_router)
router.include_router(restore_file_revision_router)
router.include_router(update_file_router)
router.include_router(withdraw_file_router)

__all__ = ["router"]
