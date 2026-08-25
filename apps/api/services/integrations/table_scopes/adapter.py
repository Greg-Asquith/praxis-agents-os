# apps/api/services/integrations/table_scopes/adapter.py

"""Provider adapter contract for the shared table row-scope engine."""

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Protocol

from .domain import (
    EligibleTableScopeColumn,
    TableCoordinate,
    TableScopeColumnType,
    TableScopeQueryParameter,
    TableScopeRewriteError,
    TableScopeValueError,
)

if TYPE_CHECKING:
    from sqlglot import exp


class TableScopeAdapter(Protocol):
    """Supplies only the SQL dialect behavior that the neutral engine needs."""

    dialect: str

    def eligible_columns(
        self,
        schema_fields: Sequence[Mapping[str, object]],
    ) -> tuple[EligibleTableScopeColumn, ...]: ...

    def validate_allowed_values(
        self,
        *,
        column_type: TableScopeColumnType,
        values: tuple[str, ...],
    ) -> None:
        """Raises TableScopeValueError when values exceed provider limits."""

    def should_skip_reference(self, table: TableCoordinate) -> bool: ...

    def validate_governed_table(self, table: "exp.Table") -> None:
        """Raise TableScopeRewriteError for unsupported table modifiers."""

    def membership_predicate(
        self,
        *,
        column_name: str,
        parameter_name: str,
    ) -> "exp.Expression": ...

    def query_parameter(
        self,
        *,
        name: str,
        column_type: TableScopeColumnType,
        values: tuple[str, ...],
    ) -> TableScopeQueryParameter: ...


__all__ = ["TableScopeAdapter", "TableScopeRewriteError", "TableScopeValueError"]
