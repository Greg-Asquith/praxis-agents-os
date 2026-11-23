# apps/api/routes/web/save_fetched_page.py

"""Save a fetched page into Files from a conversation's tool card."""

from fastapi import APIRouter, Depends, Request

from core.dependencies import (
    AsyncDbSessionDep,
    CurrentUserDep,
    CurrentWorkspaceDep,
    require_editor,
)
from core.rate_limiting import require_rate_limit
from services.web.save_fetched_page import save_fetched_page as save_fetched_page_service
from services.web.schemas import FetchedPageSaveCreate, FetchedPageSaveRead

# Each call sends a request to a public site, so the limit bounds what one client can send.
router = APIRouter(
    dependencies=[
        Depends(require_editor),
        Depends(require_rate_limit(custom_limit=30, custom_window=60)),
    ]
)


@router.post("/page-saves")
async def save_fetched_page(
    payload: FetchedPageSaveCreate,
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> FetchedPageSaveRead:
    workspace, _membership = workspace_context
    return await save_fetched_page_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        conversation_id=payload.conversation_id,
        url=payload.url,
    )
