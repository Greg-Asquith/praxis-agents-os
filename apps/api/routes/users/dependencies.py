# apps/api/routes/users/dependencies.py

"""Dependencies for user-management routes."""

from typing import Annotated

from fastapi import Depends

from core.dependencies import require_super_admin
from models.user import User

SuperAdminDep = Annotated[User, Depends(require_super_admin)]
