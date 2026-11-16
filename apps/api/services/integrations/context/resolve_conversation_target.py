# apps/api/services/integrations/context/resolve_conversation_target.py

"""Resolve the one active context target a person's conversation request names."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationValidationError
from models.user import User
from models.workspace import Workspace
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.get_active_context_selection import (
    get_active_context_selection,
)
from services.integrations.context.resolve_active_context import resolve_active_context_targets
from services.integrations.context.schemas import ActiveContextSelectionValue


async def resolve_conversation_target(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    conversation_id: UUID,
    provider_key: str,
    scope_id: str,
    operation: str,
) -> ResolvedContextEntry:
    """Fails before credentials unless exactly one selected target matches."""
    selections = await get_active_context_selection(
        db, actor=actor, workspace=workspace, conversation_id=conversation_id
    )
    resolved = await resolve_active_context_targets(
        db,
        selections=[
            ActiveContextSelectionValue.from_selection(selection) for selection in selections
        ],
        user=actor,
        workspace=workspace,
    )
    matches = [
        entry
        for entry in resolved.entries
        if entry.provider_key == provider_key and entry.external_id == scope_id
    ]
    if len(matches) != 1:
        raise IntegrationValidationError(
            "The target is unavailable in this conversation's selected connections",
            provider_key=provider_key,
            operation=operation,
        )
    return matches[0]
