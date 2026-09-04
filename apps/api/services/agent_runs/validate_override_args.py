# apps/api/services/agent_runs/validate_override_args.py

"""Server-side enforcement for governed tool argument overrides."""

import json
import math
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.agent_run import AgentRun
from models.user import User
from models.workspace import Workspace, WorkspaceMembership

if TYPE_CHECKING:
    from services.agents.runtime.tools.contract import RuntimeToolDefinition, ToolFieldColumn


async def validate_and_canonicalize_override_args(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    run: AgentRun,
    tool_call: Any,
    override_args: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Reject locked edits and re-resolve every entity reference before resume."""
    from services.agents.runtime.tools.registry import get_runtime_tool_definition

    tool_name = str(getattr(tool_call, "tool_name", ""))
    definition = get_runtime_tool_definition(tool_name)
    if definition is None:
        raise AppValidationError(
            "The pending tool is no longer available. Ask the agent to generate it again.",
            field="decisions",
            details={"tool_name": tool_name},
        )
    original_args = _original_tool_args(tool_call, tool_name=tool_name)
    effective_args = dict(override_args) if override_args is not None else dict(original_args)
    _validate_locked_changes(
        definition,
        original_args=original_args,
        effective_args=effective_args,
        tool_name=tool_name,
    )
    _validate_record_fields(definition, effective_args=effective_args)
    await _canonicalize_entity_fields(
        db,
        actor=actor,
        workspace=workspace,
        membership=membership,
        run=run,
        definition=definition,
        effective_args=effective_args,
        tool_name=tool_name,
    )
    return effective_args if override_args is not None or effective_args != original_args else None


def _original_tool_args(tool_call: Any, *, tool_name: str) -> dict[str, Any]:
    original = getattr(tool_call, "args", None)
    if isinstance(original, str):
        try:
            original = json.loads(original)
        except json.JSONDecodeError:
            original = None
    if isinstance(original, Mapping):
        return dict(original)
    raise AppValidationError(
        "The pending tool arguments cannot be edited safely. Ask the agent to generate them again.",
        field="decisions",
        details={"tool_name": tool_name},
    )


def _validate_locked_changes(
    definition: "RuntimeToolDefinition",
    *,
    original_args: Mapping[str, Any],
    effective_args: Mapping[str, Any],
    tool_name: str,
) -> None:
    fields = {field.key: field for field in definition.presentation.arg_fields}
    changed_keys = {
        key
        for key in set(original_args).union(effective_args)
        if key not in original_args
        or key not in effective_args
        or original_args[key] != effective_args[key]
    }
    locked_changes = sorted(
        key for key in changed_keys if key not in fields or not fields[key].editable
    )
    if locked_changes:
        raise AppValidationError(
            "One or more tool fields are not editable",
            field="override_args",
            details={"tool_name": tool_name, "locked_fields": locked_changes},
        )


def _validate_record_fields(
    definition: "RuntimeToolDefinition", *, effective_args: Mapping[str, Any]
) -> None:
    for field in definition.presentation.arg_fields:
        if field.format == "records" and field.editable:
            if field.secondary and field.key not in effective_args:
                continue
            _validate_records_override(
                field_key=field.key,
                value=effective_args.get(field.key),
                columns=field.columns,
                min_rows=field.min_rows,
            )


async def _canonicalize_entity_fields(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    run: AgentRun,
    definition: "RuntimeToolDefinition",
    effective_args: dict[str, Any],
    tool_name: str,
) -> None:
    from services.agents.runtime.entity_references.service import (
        authorize_entity_field,
        resolve_authorized_references,
    )

    for field in definition.presentation.arg_fields:
        if field.format not in {"entity", "entity_list"}:
            continue
        value = effective_args.get(field.key)
        if field.secondary and value is None:
            continue
        values = value if field.format == "entity_list" and isinstance(value, list) else [value]
        if field.format == "entity_list" and (
            not isinstance(value, list) or not value or len(value) > 500
        ):
            raise AppValidationError(
                "Entity list selections must contain between 1 and 500 targets",
                field=field.key,
            )
        if field.format == "entity" and not isinstance(value, Mapping):
            raise AppValidationError(
                "This pending approval uses an older raw target identifier. "
                "Ask the agent to generate the request again.",
                field=field.key,
                details={"tool_name": tool_name, "entity_kind": field.entity_kind},
            )
        authorized = await authorize_entity_field(
            db,
            actor=actor,
            workspace=workspace,
            membership=membership,
            conversation_id=run.conversation_id,
            tool_name=tool_name,
            field_key=field.key,
            run=run,
        )
        canonical = await resolve_authorized_references(
            authorized,
            values=values,
            dependent_args=effective_args,
        )
        effective_args[field.key] = canonical if field.format == "entity_list" else canonical[0]


def _validate_records_override(
    *,
    field_key: str,
    value: Any,
    columns: tuple["ToolFieldColumn", ...],
    min_rows: int,
) -> None:
    from services.agents.runtime.tools.contract import RECORDS_FIELD_MAX_ROWS

    if not isinstance(value, list):
        raise AppValidationError(
            "Record fields must be a list of rows",
            field=field_key,
        )
    if len(value) > RECORDS_FIELD_MAX_ROWS:
        raise AppValidationError(
            f"Record fields cannot contain more than {RECORDS_FIELD_MAX_ROWS} rows",
            field=field_key,
        )
    if len(value) < min_rows:
        raise AppValidationError(
            f"Record fields must contain at least {min_rows} row{'s' if min_rows != 1 else ''}",
            field=field_key,
        )

    declared_keys = {column.key for column in columns}
    required_columns = {column.key for column in columns if column.required}
    columns_by_key = {column.key: column for column in columns}
    for row_index, row in enumerate(value):
        _validate_record_row(
            field_key=field_key,
            row=row,
            row_index=row_index,
            declared_keys=declared_keys,
            required_columns=required_columns,
            columns_by_key=columns_by_key,
        )


def _validate_record_row(
    *,
    field_key: str,
    row: Any,
    row_index: int,
    declared_keys: set[str],
    required_columns: set[str],
    columns_by_key: Mapping[str, "ToolFieldColumn"],
) -> None:
    if (
        not isinstance(row, Mapping)
        or not set(row).issubset(declared_keys)
        or not required_columns.issubset(row)
    ):
        raise AppValidationError(
            "Every record row must contain required columns and no undeclared columns",
            field=field_key,
            details={"row": row_index},
        )
    for column_key, item in row.items():
        _validate_record_cell(
            field_key=field_key,
            row_index=row_index,
            column=columns_by_key[column_key],
            item=item,
        )


def _validate_record_cell(
    *, field_key: str, row_index: int, column: "ToolFieldColumn", item: Any
) -> None:
    details = {"column": column.key, "row": row_index}
    if not _record_cell_matches_format(column, item):
        raise AppValidationError(
            "A record cell does not match its declared format",
            field=field_key,
            details=details,
        )
    if isinstance(item, float) and not math.isfinite(item):
        raise AppValidationError("Record numbers must be finite", field=field_key, details=details)
    if column.required and isinstance(item, str) and not item.strip():
        raise AppValidationError(
            "Required record cells must not be blank", field=field_key, details=details
        )
    if column.required and isinstance(item, (list, Mapping)) and not item:
        raise AppValidationError(
            "Required record cells must not be empty", field=field_key, details=details
        )
    if column.options and item not in column.options:
        raise AppValidationError(
            "A record cell is not one of the allowed options",
            field=field_key,
            details=details,
        )
    if (
        column.max_entries is not None
        and isinstance(item, Mapping)
        and len(item) > column.max_entries
    ):
        raise AppValidationError(
            f"A record cell cannot contain more than {column.max_entries} entries",
            field=field_key,
            details=details,
        )


def _record_cell_matches_format(column: "ToolFieldColumn", item: Any) -> bool:
    if column.format in {"text", "number"}:
        return not isinstance(item, bool) and isinstance(item, str | int | float)
    if column.format == "list":
        return isinstance(item, list) and all(isinstance(entry, str) for entry in item)
    if column.format == "keyvalue":
        return isinstance(item, Mapping) and all(
            isinstance(key, str) and _is_scalar_mapping_value(entry) for key, entry in item.items()
        )
    return False


def _is_scalar_mapping_value(value: Any) -> bool:
    return isinstance(value, str | bool) or (
        not isinstance(value, bool) and isinstance(value, int | float) and math.isfinite(value)
    )
