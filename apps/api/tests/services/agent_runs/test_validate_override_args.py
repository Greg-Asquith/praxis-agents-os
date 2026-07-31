"""Security-boundary tests for governed tool argument overrides."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from core.exceptions.general import AppValidationError
from services.agent_runs.validate_override_args import validate_and_canonicalize_override_args

pytestmark = pytest.mark.asyncio


def _call(tool_name: str, args: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(tool_name=tool_name, args=args)


async def test_locked_field_override_is_rejected() -> None:
    with pytest.raises(AppValidationError, match="not editable") as exc_info:
        await validate_and_canonicalize_override_args(
            AsyncMock(),
            actor=SimpleNamespace(),
            workspace=SimpleNamespace(),
            membership=SimpleNamespace(),
            run=SimpleNamespace(conversation_id=uuid4()),
            tool_call=_call(
                "create_artifact",
                {"title": "Plan", "artifact_type": "document", "content": "Draft"},
            ),
            override_args={
                "title": "Plan",
                "artifact_type": "code",
                "content": "Draft",
            },
        )

    assert exc_info.value.details["locked_fields"] == ["artifact_type"]


async def test_declared_editable_field_override_is_preserved() -> None:
    override = {
        "title": "Revised plan",
        "artifact_type": "document",
        "content": "Draft",
    }

    result = await validate_and_canonicalize_override_args(
        AsyncMock(),
        actor=SimpleNamespace(),
        workspace=SimpleNamespace(),
        membership=SimpleNamespace(),
        run=SimpleNamespace(conversation_id=uuid4()),
        tool_call=_call(
            "create_artifact",
            {"title": "Plan", "artifact_type": "document", "content": "Draft"},
        ),
        override_args=override,
    )

    assert result == override


async def test_entity_field_rejects_legacy_raw_identifier() -> None:
    with pytest.raises(AppValidationError, match="older raw target identifier"):
        await validate_and_canonicalize_override_args(
            AsyncMock(),
            actor=SimpleNamespace(),
            workspace=SimpleNamespace(),
            membership=SimpleNamespace(),
            run=SimpleNamespace(conversation_id=uuid4()),
            tool_call=_call("read_file", {"file_id": str(uuid4()), "mode": "content"}),
            override_args=None,
        )


async def test_entity_override_is_reauthorized_and_canonicalized(monkeypatch) -> None:
    original_id = uuid4()
    selected_id = uuid4()
    original = {
        "version": 1,
        "entity_kind": "file",
        "entity_id": str(original_id),
        "label": "Old label",
        "description": None,
        "scope_label": None,
    }
    selected = {**original, "entity_id": str(selected_id), "label": "Browser hint"}
    canonical = {**selected, "label": "Canonical file name"}
    authorize = AsyncMock(return_value=SimpleNamespace())
    resolve = AsyncMock(return_value=[canonical])
    monkeypatch.setattr(
        "services.agents.runtime.entity_references.service.authorize_entity_field",
        authorize,
    )
    monkeypatch.setattr(
        "services.agents.runtime.entity_references.service.resolve_authorized_references",
        resolve,
    )

    run = SimpleNamespace(conversation_id=uuid4())
    result = await validate_and_canonicalize_override_args(
        AsyncMock(),
        actor=SimpleNamespace(),
        workspace=SimpleNamespace(),
        membership=SimpleNamespace(),
        run=run,
        tool_call=_call("read_file", {"file_id": original, "mode": "content"}),
        override_args={"file_id": selected, "mode": "content"},
    )

    assert result == {"file_id": canonical, "mode": "content"}
    authorize.assert_awaited_once()
    assert authorize.await_args.kwargs["run"] is run
    resolve.assert_awaited_once()
