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
    from services.agents.runtime.tools.contract import ToolFieldColumn


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
    from services.agents.runtime.entity_references.service import (
        authorize_entity_field,
        resolve_authorized_references,
    )
    from services.agents.runtime.tools.registry import get_runtime_tool_definition

    tool_name = str(getattr(tool_call, "tool_name", ""))
    definition = get_runtime_tool_definition(tool_name)
    if definition is None:
        raise AppValidationError(
            "The pending tool is no longer available. Ask the agent to generate it again.",
            field="decisions",
            details={"tool_name": tool_name},
        )
    original = getattr(tool_call, "args", None)
    if isinstance(original, str):
        try:
            original = json.loads(original)
        except json.JSONDecodeError:
            original = None
    if not isinstance(original, Mapping):
        raise AppValidationError(
            "The pending tool arguments cannot be edited safely. Ask the agent to generate them again.",
            field="decisions",
            details={"tool_name": tool_name},
        )
    original_args = dict(original)
    effective_args = dict(override_args) if override_args is not None else dict(original_args)
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

    for field in definition.presentation.arg_fields:
        if field.format == "records" and field.editable:
            _validate_records_override(
                field_key=field.key,
                value=effective_args.get(field.key),
                columns=field.columns,
                min_rows=field.min_rows,
            )

    for field in definition.presentation.arg_fields:
        if field.format not in {"entity", "entity_list"}:
            continue
        value = effective_args.get(field.key)
        if field.secondary and value is None:
            continue
        values = value if field.format == "entity_list" and isinstance(value, list) else [value]
        if field.format == "entity_list" and (
            not isinstance(value, list) or not value or len(value) > 50
        ):
            raise AppValidationError(
                "Entity list selections must contain between 1 and 50 targets",
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

    return effective_args if override_args is not None or effective_args != original_args else None


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
    constrained_options = {
        column.key: frozenset(column.options) for column in columns if column.options
    }
    required_columns = {column.key for column in columns if column.required}
    for row_index, row in enumerate(value):
        if not isinstance(row, Mapping) or set(row) != declared_keys:
            raise AppValidationError(
                "Every record row must contain exactly the declared columns",
                field=field_key,
                details={"row": row_index},
            )
        for column_key, item in row.items():
            if isinstance(item, bool) or not isinstance(item, str | int | float):
                raise AppValidationError(
                    "Record cells must be text or numbers",
                    field=field_key,
                    details={"column": column_key, "row": row_index},
                )
            if isinstance(item, float) and not math.isfinite(item):
                raise AppValidationError(
                    "Record numbers must be finite",
                    field=field_key,
                    details={"column": column_key, "row": row_index},
                )
            if column_key in required_columns and isinstance(item, str) and not item.strip():
                raise AppValidationError(
                    "Required record cells must not be blank",
                    field=field_key,
                    details={"column": column_key, "row": row_index},
                )
            options = constrained_options.get(column_key)
            if options is not None and item not in options:
                raise AppValidationError(
                    "A record cell is not one of the allowed options",
                    field=field_key,
                    details={"column": column_key, "row": row_index},
                )
