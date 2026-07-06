# apps/api/routes/files/__init__.py

"""Workspace file route registry."""

from fastapi import APIRouter

from routes.files.confirm_file_upload import router as confirm_file_upload_router
from routes.files.create_file_download import router as create_file_download_router
from routes.files.create_file_upload import router as create_file_upload_router
from routes.files.delete_file import router as delete_file_router
from routes.files.edit_file import router as edit_file_router
from routes.files.get_file import router as get_file_router
from routes.files.get_file_revision_content import router as get_file_revision_content_router
from routes.files.get_files_processing import router as get_files_processing_router
from routes.files.get_files_usage import router as get_files_usage_router
from routes.files.list_file_revisions import router as list_file_revisions_router
from routes.files.list_files import router as list_files_router
from routes.files.purge_file import router as purge_file_router
from routes.files.restore_file_revision import router as restore_file_revision_router
from routes.files.update_file import router as update_file_router

router = APIRouter(prefix="/files", tags=["files"])
router.include_router(create_file_upload_router)
router.include_router(confirm_file_upload_router)
router.include_router(list_files_router)
router.include_router(get_files_processing_router)
router.include_router(get_files_usage_router)
router.include_router(get_file_router)
router.include_router(update_file_router)
router.include_router(delete_file_router)
router.include_router(purge_file_router)
router.include_router(edit_file_router)
router.include_router(restore_file_revision_router)
router.include_router(list_file_revisions_router)
router.include_router(get_file_revision_content_router)
router.include_router(create_file_download_router)

__all__ = ["router"]
