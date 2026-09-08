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
from integrations.google_ads.tools.update_positive_keywords import (
    DEFINITION as GOOGLE_ADS_UPDATE_KEYWORDS_DEFINITION,
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
                            default_value="EXACT",
                        ),
                        ToolFieldColumn(key="tags", label="Tags", format="list"),
                        ToolFieldColumn(
                            key="attributes", label="Attributes", format="keyvalue", max_entries=3
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


async def test_positive_keyword_update_resume_preserves_edited_positional_rows(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.agents.runtime.tools.registry.get_runtime_tool_definition",
        lambda _tool_name: GOOGLE_ADS_UPDATE_KEYWORDS_DEFINITION,
    )
    keywords = [
        {
            "version": 1,
            "entity_kind": "google_ads_keyword",
            "customer_id": "333",
            "campaign_id": "10",
            "ad_group_id": ad_group_id,
            "criterion_id": "90",
            "text": "running shoes",
            "match_type": "EXACT",
            "status": status,
            "cpc_bid_micros": None,
            "label": "running shoes",
            "description": "Exact",
            "scope_label": scope_label,
        }
        for ad_group_id, status, scope_label in (
            ("20", "PAUSED", "Search · Shoes"),
            ("30", "ENABLED", "Search · Boots"),
        )
    ]
    canonical = [{**value, "label": f"Canonical {index}"} for index, value in enumerate(keywords)]
    authorize = AsyncMock(return_value=SimpleNamespace())
    resolve = AsyncMock(return_value=canonical)
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
            "google_ads_update_keywords",
            {"keywords": keywords, "patches": [{"status": "PAUSED"}, {"status": "ENABLED"}]},
        ),
        override_args={
            "keywords": keywords,
            "patches": [{"status": "ENABLED"}, {"status": "PAUSED"}],
        },
    )

    assert result == {
        "keywords": canonical,
        "patches": [{"status": "ENABLED"}, {"status": "PAUSED"}],
    }
    resolve.assert_awaited_once()


@pytest.mark.parametrize(
    ("rows", "error"),
    [
        (
            [{"text": "new", "match_type": "EXACT", "undeclared": "value"}],
            "no undeclared columns",
        ),
        ([{"text": "new", "match_type": "BROAD"}], "allowed options"),
        ([{"text": ["nested"], "match_type": "EXACT"}], "declared format"),
        (
            [{"text": "new", "match_type": "EXACT", "tags": ["valid", 2]}],
            "declared format",
        ),
        (
            [
                {
                    "text": "new",
                    "match_type": "EXACT",
                    "attributes": {"nested": {"value": "invalid"}},
                }
            ],
            "declared format",
        ),
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


async def test_records_override_accepts_list_and_keyvalue_cells(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.agents.runtime.tools.registry.get_runtime_tool_definition",
        lambda _tool_name: _records_definition(),
    )
    rows = [
        {
            "text": "new",
            "match_type": "EXACT",
            "tags": ["brand", "priority"],
            "attributes": {"enabled": True, "score": 2.5, "note": "reviewed"},
        }
    ]

    result = await validate_and_canonicalize_override_args(
        AsyncMock(),
        actor=SimpleNamespace(),
        workspace=SimpleNamespace(),
        membership=SimpleNamespace(),
        run=SimpleNamespace(conversation_id=uuid4()),
        tool_call=_call("records_write", {"rows": [{"text": "old", "match_type": "EXACT"}]}),
        override_args={"rows": rows},
    )

    assert result == {"rows": rows}


@pytest.mark.parametrize(
    ("rows", "error"),
    [
        ([], "at least 1 row"),
        ([{"match_type": "EXACT"}], "required columns"),
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


async def test_records_approval_allows_an_omitted_optional_column(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.agents.runtime.tools.registry.get_runtime_tool_definition",
        lambda _tool_name: _records_definition(min_rows=1, required_text=True),
    )
    rows = [{"text": "keyword"}]

    result = await validate_and_canonicalize_override_args(
        AsyncMock(),
        actor=SimpleNamespace(),
        workspace=SimpleNamespace(),
        membership=SimpleNamespace(),
        run=SimpleNamespace(conversation_id=uuid4()),
        tool_call=_call("records_write", {"rows": rows}),
        override_args=None,
    )

    assert result is None


async def test_records_approval_enforces_declared_keyvalue_entry_limit(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.agents.runtime.tools.registry.get_runtime_tool_definition",
        lambda _tool_name: _records_definition(min_rows=1, required_text=True),
    )
    with pytest.raises(AppValidationError, match="more than 3 entries"):
        await validate_and_canonicalize_override_args(
            AsyncMock(),
            actor=SimpleNamespace(),
            workspace=SimpleNamespace(),
            membership=SimpleNamespace(),
            run=SimpleNamespace(conversation_id=uuid4()),
            tool_call=_call(
                "records_write",
                {
                    "rows": [
                        {
                            "text": "keyword",
                            "attributes": {"a": "1", "b": "2", "c": "3", "d": "4"},
                        }
                    ]
                },
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


def _scalar_tool(value: str | bool | None = None) -> str:
    return str(value)


@pytest.fixture
def scalar_definition(monkeypatch):
    def configure(format, *, secondary=False):
        definition = RuntimeToolDefinition(
            name="scalar_write",
            function=_scalar_tool,
            description="Review a scalar.",
            presentation=ToolPresentation(
                arg_fields=(
                    ToolFieldPresentation(
                        key="value",
                        label="Value",
                        format=format,
                        editable=True,
                        secondary=secondary,
                    ),
                )
            ),
        )
        monkeypatch.setattr(
            "services.agents.runtime.tools.registry.get_runtime_tool_definition",
            lambda _name: definition,
        )

    return configure


@pytest.mark.parametrize(
    "format,value",
    [
        ("datetime", "2026-09-08T09:30"),
        ("datetime", "2024-02-29T09:30:45"),
        ("boolean", True),
        ("boolean", False),
    ],
)
@pytest.mark.parametrize("edited", [False, True])
async def test_scalar_approval_preserves_exact_values(scalar_definition, format, value, edited):
    scalar_definition(format)
    args = {"value": value}
    result = await validate_and_canonicalize_override_args(
        AsyncMock(),
        actor=SimpleNamespace(),
        workspace=SimpleNamespace(),
        membership=SimpleNamespace(),
        run=SimpleNamespace(),
        tool_call=_call("scalar_write", {"value": None} if edited else args),
        override_args=args if edited else None,
    )
    assert result == (args if edited else None)
    if edited:
        assert type(result["value"]) is type(value)


@pytest.mark.parametrize(
    "format,value",
    [
        ("datetime", "2026-09-08T09:30+01:00"),
        ("datetime", "2026-09-08T09:30Z"),
        ("datetime", "2026-02-30T09:30"),
        ("datetime", "2026-09-08T24:00"),
        ("datetime", "2026-09-08T09:30:60"),
        ("datetime", "2026-09-08T09:30:00.123"),
        ("datetime", "2026-09-08 09:30"),
        ("datetime", "2026-09-08"),
        ("datetime", "2026-09-08T09:30\n"),
        ("datetime", 123),
        ("datetime", None),
        ("datetime", ""),
        ("boolean", "true"),
        ("boolean", "false"),
        ("boolean", 1),
        ("boolean", 0),
        ("boolean", None),
    ],
)
@pytest.mark.parametrize("edited", [False, True])
async def test_scalar_approval_rejects_malformed_effective_values(
    scalar_definition, format, value, edited
):
    scalar_definition(format)
    error = (
        "Date and time must be in the form YYYY-MM-DDTHH:MM"
        if format == "datetime"
        else "This field must be on or off"
    )
    with pytest.raises(AppValidationError, match=error) as exc_info:
        await validate_and_canonicalize_override_args(
            AsyncMock(),
            actor=SimpleNamespace(),
            workspace=SimpleNamespace(),
            membership=SimpleNamespace(),
            run=SimpleNamespace(),
            tool_call=_call("scalar_write", {"value": value}),
            override_args={"value": value} if edited else None,
        )
    assert exc_info.value.field == "value"


@pytest.mark.parametrize("format", ["datetime", "boolean"])
@pytest.mark.parametrize("args", [{}, {"value": None}])
@pytest.mark.parametrize("secondary", [False, True])
async def test_scalar_approval_requires_only_primary_values(
    scalar_definition, format, args, secondary
):
    scalar_definition(format, secondary=secondary)

    async def validate():
        return await validate_and_canonicalize_override_args(
            AsyncMock(),
            actor=SimpleNamespace(),
            workspace=SimpleNamespace(),
            membership=SimpleNamespace(),
            run=SimpleNamespace(),
            tool_call=_call("scalar_write", args),
            override_args=None,
        )

    if secondary:
        assert await validate() is None
    else:
        with pytest.raises(AppValidationError):
            await validate()
