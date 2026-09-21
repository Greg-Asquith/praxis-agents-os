"""Run authority is checked before entity tools or providers are resolved."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from core.exceptions.general import AppValidationError
from services.agents.runtime.entity_references.service import authorize_entity_field


@pytest.mark.parametrize("invalid_field", ["conversation_id", "workspace_id", "deleted"])
async def test_explicit_run_must_belong_to_live_conversation(monkeypatch, invalid_field):
    conversation = SimpleNamespace(id=uuid4())
    workspace = SimpleNamespace(id=uuid4())
    run = SimpleNamespace(
        id=uuid4(), conversation_id=conversation.id, workspace_id=workspace.id, deleted=False
    )
    setattr(run, invalid_field, True if invalid_field == "deleted" else uuid4())
    conversation_lookup = AsyncMock(return_value=conversation)
    monkeypatch.setattr(
        "services.agents.runtime.entity_references.service.get_conversation_for_actor",
        conversation_lookup,
    )
    db = AsyncMock()
    actor = SimpleNamespace(id=uuid4())

    with pytest.raises(AppValidationError, match="not available in this conversation") as error:
        await authorize_entity_field(
            db,
            actor=actor,
            workspace=workspace,
            membership=SimpleNamespace(),
            conversation_id=conversation.id,
            tool_name="sharepoint_create_file",
            field_key="parent",
            run=run,
        )

    assert error.value.details["run_id"] == str(run.id)
    conversation_lookup.assert_awaited_once_with(
        db, actor=actor, workspace=workspace, conversation_id=conversation.id
    )
    db.scalar.assert_not_awaited()
