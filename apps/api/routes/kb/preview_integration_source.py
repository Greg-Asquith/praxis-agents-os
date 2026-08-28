# apps/api/routes/kb/preview_integration_source.py

"""Preview an integration source for Knowledge Base import."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.dependencies import (
    AsyncDbSessionDep,
    CurrentUserDep,
    CurrentWorkspaceDep,
    require_editor,
)
from services.integrations.plugin import KnowledgeSourcePreview
from services.kb.integration_sources import preview_integration_knowledge_source

router = APIRouter(dependencies=[Depends(require_editor)])


class KBIntegrationSourcePreviewRequest(BaseModel):
    """Knowledge Base integration source preview request."""

    integration_resource_id: UUID
    source: str | dict[str, Any]


@router.post("/integration-sources/preview")
async def preview_source(
    body: KBIntegrationSourcePreviewRequest,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> KnowledgeSourcePreview:
    workspace, membership = workspace_context
    return await preview_integration_knowledge_source(
        db,
        integration_resource_id=body.integration_resource_id,
        actor=actor,
        workspace=workspace,
        membership=membership,
        source=body.source,
    )
