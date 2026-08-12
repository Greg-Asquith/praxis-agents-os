"""Security-boundary tests for governed tool argument overrides."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from core.exceptions.general import AppValidationError
from integrations.google_ads.tools.add_negative_keywords import (
    DEFINITION as GOOGLE_ADS_ADD_NEGATIVE_KEYWORDS_DEFINITION,
)
from integrations.google_ads.tools.remove_negative_keywords import (
    DEFINITION as GOOGLE_ADS_REMOVE_NEGATIVE_KEYWORDS_DEFINITION,
)
from services.agent_runs.validate_override_args import validate_and_canonicalize_override_args
from services.agents.runtime.tools.contract import (
    RECORDS_FIELD_MAX_ROWS,
    RuntimeToolDefinition,
    ToolFieldColumn,
    ToolFieldPresentation,
    ToolPresentation,
)

pytestmark = pytest.mark.asyncio


def _call(tool_name: str, args: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(tool_name=tool_name, args=args)


def _records_tool(_rows: list[dict[str, str | int | float]]) -> str:
    return "ok"


def _records_definition(
    *,
    editable: bool = True,
    min_rows: int = 0,
    required_text: bool = False,
    required_match_type: bool = False,
) -> RuntimeToolDefinition:
    return RuntimeToolDefinition(
        name="records_write",
        function=_records_tool,
        description="Write declared records.",
        presentation=ToolPresentation(
            arg_fields=(
                ToolFieldPresentation(
                    key="rows",
                    label="Rows",
                    format="records",
                    editable=editable,
                    min_rows=min_rows,
                    columns=(
                        ToolFieldColumn(key="text", label="Text", required=required_text),
                        ToolFieldColumn(
                            key="match_type",
                            label="Match Type",
                            options=("EXACT", "PHRASE"),
                            required=required_match_type,
                        ),
                    ),
                ),
            )
        ),
    )


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


async def test_records_override_preserves_the_exact_edited_rows(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.agents.runtime.tools.registry.get_runtime_tool_definition",
        lambda _tool_name: _records_definition(),
    )
    original = [{"text": "old", "match_type": "EXACT"}]
    override = [
        {"text": "new", "match_type": "PHRASE"},
        {"text": "numeric marker", "match_type": "EXACT"},
    ]

    result = await validate_and_canonicalize_override_args(
        AsyncMock(),
        actor=SimpleNamespace(),
        workspace=SimpleNamespace(),
        membership=SimpleNamespace(),
        run=SimpleNamespace(conversation_id=uuid4()),
        tool_call=_call("records_write", {"rows": original}),
        override_args={"rows": override},
    )

    assert result == {"rows": override}


@pytest.mark.parametrize(
    ("definition", "tool_name", "edited_rows"),
    [
        (
            GOOGLE_ADS_ADD_NEGATIVE_KEYWORDS_DEFINITION,
            "google_ads_add_negative_keywords",
            [
                {"text": "replacement", "match_type": "PHRASE"},
                {"text": "added row", "match_type": "BROAD"},
            ],
        ),
        (
            GOOGLE_ADS_REMOVE_NEGATIVE_KEYWORDS_DEFINITION,
            "google_ads_remove_negative_keywords",
            [
                {"text": "replacement", "match_type": "PHRASE"},
                {"text": "all variants", "match_type": "ANY"},
            ],
        ),
    ],
)
async def test_google_ads_keyword_override_reauthorizes_list_and_preserves_edited_rows(
    monkeypatch, definition, tool_name: str, edited_rows
) -> None:
    monkeypatch.setattr(
        "services.agents.runtime.tools.registry.get_runtime_tool_definition",
        lambda _tool_name: definition,
    )
    original_list = {
        "version": 1,
        "entity_kind": "google_ads_shared_set",
        "integration_resource_id": str(uuid4()),
        "external_id": "50",
        "label": "Old list",
        "description": None,
        "scope_label": "Account",
        "member_count": 2,
    }
    selected_list = {**original_list, "external_id": "60", "label": "Browser hint"}
    canonical_list = {**selected_list, "label": "Canonical list", "member_count": 3}
    authorize = AsyncMock(return_value=SimpleNamespace())
    resolve = AsyncMock(return_value=[canonical_list])
    monkeypatch.setattr(
        "services.agents.runtime.entity_references.service.authorize_entity_field",
        authorize,
    )
    monkeypatch.setattr(
        "services.agents.runtime.entity_references.service.resolve_authorized_references",
        resolve,
    )
    result = await validate_and_canonicalize_override_args(
        AsyncMock(),
        actor=SimpleNamespace(),
        workspace=SimpleNamespace(),
        membership=SimpleNamespace(),
        run=SimpleNamespace(conversation_id=uuid4()),
        tool_call=_call(
            tool_name,
            {
                "negative_list": original_list,
                "keywords": [{"text": "remove me", "match_type": "EXACT"}],
            },
        ),
        override_args={"negative_list": selected_list, "keywords": edited_rows},
    )

    assert result == {"negative_list": canonical_list, "keywords": edited_rows}
    authorize.assert_awaited_once()
    resolve.assert_awaited_once()


@pytest.mark.parametrize(
    ("rows", "error"),
    [
        (
            [{"text": "new", "match_type": "EXACT", "undeclared": "value"}],
            "exactly the declared columns",
        ),
        ([{"text": "new", "match_type": "BROAD"}], "allowed options"),
        ([{"text": ["nested"], "match_type": "EXACT"}], "text or numbers"),
        (
            [{"text": "row", "match_type": "EXACT"}] * (RECORDS_FIELD_MAX_ROWS + 1),
            "cannot contain more than",
        ),
    ],
)
async def test_records_override_rejects_invalid_rows(monkeypatch, rows, error: str) -> None:
    monkeypatch.setattr(
        "services.agents.runtime.tools.registry.get_runtime_tool_definition",
        lambda _tool_name: _records_definition(),
    )

    with pytest.raises(AppValidationError, match=error):
        await validate_and_canonicalize_override_args(
            AsyncMock(),
            actor=SimpleNamespace(),
            workspace=SimpleNamespace(),
            membership=SimpleNamespace(),
            run=SimpleNamespace(conversation_id=uuid4()),
            tool_call=_call(
                "records_write",
                {"rows": [{"text": "old", "match_type": "EXACT"}]},
            ),
            override_args={"rows": rows},
        )


@pytest.mark.parametrize(
    ("rows", "error"),
    [
        ([], "at least 1 row"),
        ([{"text": "   ", "match_type": "EXACT"}], "must not be blank"),
    ],
)
async def test_records_override_enforces_declared_completeness(
    monkeypatch, rows, error: str
) -> None:
    monkeypatch.setattr(
        "services.agents.runtime.tools.registry.get_runtime_tool_definition",
        lambda _tool_name: _records_definition(min_rows=1, required_text=True),
    )

    with pytest.raises(AppValidationError, match=error):
        await validate_and_canonicalize_override_args(
            AsyncMock(),
            actor=SimpleNamespace(),
            workspace=SimpleNamespace(),
            membership=SimpleNamespace(),
            run=SimpleNamespace(conversation_id=uuid4()),
            tool_call=_call(
                "records_write",
                {"rows": [{"text": "old", "match_type": "EXACT"}]},
            ),
            override_args={"rows": rows},
        )


async def test_records_approval_enforces_completeness_without_an_override(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.agents.runtime.tools.registry.get_runtime_tool_definition",
        lambda _tool_name: _records_definition(min_rows=1, required_text=True),
    )

    with pytest.raises(AppValidationError, match="must not be blank"):
        await validate_and_canonicalize_override_args(
            AsyncMock(),
            actor=SimpleNamespace(),
            workspace=SimpleNamespace(),
            membership=SimpleNamespace(),
            run=SimpleNamespace(conversation_id=uuid4()),
            tool_call=_call(
                "records_write",
                {"rows": [{"text": " ", "match_type": "EXACT"}]},
            ),
            override_args=None,
        )


@pytest.mark.parametrize("text", ["", "   ", 0, -2, 1.5])
async def test_records_override_preserves_optional_blank_and_finite_numeric_cells(
    monkeypatch, text
) -> None:
    monkeypatch.setattr(
        "services.agents.runtime.tools.registry.get_runtime_tool_definition",
        lambda _tool_name: _records_definition(min_rows=1),
    )
    rows = [{"text": text, "match_type": "EXACT"}]

    result = await validate_and_canonicalize_override_args(
        AsyncMock(),
        actor=SimpleNamespace(),
        workspace=SimpleNamespace(),
        membership=SimpleNamespace(),
        run=SimpleNamespace(conversation_id=uuid4()),
        tool_call=_call(
            "records_write",
            {"rows": [{"text": "old", "match_type": "EXACT"}]},
        ),
        override_args={"rows": rows},
    )

    assert result == {"rows": rows}


async def test_locked_records_override_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.agents.runtime.tools.registry.get_runtime_tool_definition",
        lambda _tool_name: _records_definition(editable=False),
    )

    with pytest.raises(AppValidationError, match="not editable"):
        await validate_and_canonicalize_override_args(
            AsyncMock(),
            actor=SimpleNamespace(),
            workspace=SimpleNamespace(),
            membership=SimpleNamespace(),
            run=SimpleNamespace(conversation_id=uuid4()),
            tool_call=_call(
                "records_write",
                {"rows": [{"text": "old", "match_type": "EXACT"}]},
            ),
            override_args={"rows": [{"text": "new", "match_type": "PHRASE"}]},
        )
