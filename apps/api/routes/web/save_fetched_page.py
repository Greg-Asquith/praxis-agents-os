# apps/api/routes/web/save_fetched_page.py

"""Save a fetched page into Files from a conversation's tool card."""

from fastapi import APIRouter, Depends, Request

from core.dependencies import (
    AsyncDbSessionDep,
    CurrentUserDep,
    CurrentWorkspaceDep,
    require_editor,
)
from services.web.save_fetched_page import save_fetched_page as save_fetched_page_service
from services.web.schemas import FetchedPageSaveCreate, FetchedPageSaveRead

router = APIRouter(dependencies=[Depends(require_editor)])


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
