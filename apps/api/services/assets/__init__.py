# apps/api/services/assets/__init__.py

"""Asset service operations."""

from services.assets.confirm_user_avatar_upload import confirm_user_avatar_upload
from services.assets.confirm_workspace_icon_upload import confirm_workspace_icon_upload
from services.assets.create_user_avatar_upload import create_user_avatar_upload
from services.assets.create_workspace_icon_upload import create_workspace_icon_upload
from services.assets.delete_user_avatar import delete_user_avatar
from services.assets.delete_workspace_icon import delete_workspace_icon

__all__ = [
    "confirm_user_avatar_upload",
    "confirm_workspace_icon_upload",
    "create_user_avatar_upload",
    "create_workspace_icon_upload",
    "delete_user_avatar",
    "delete_workspace_icon",
]
