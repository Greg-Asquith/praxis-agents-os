# apps/api/services/integrations/table_scopes/domain.py

"""Provider-neutral values used by table row-scope adapters and rewriting."""

from dataclasses import dataclass
from typing import Literal

TableScopeColumnType = Literal["string", "integer"]


@dataclass(frozen=True, order=True)
class TableCoordinate:
    """A fully qualified warehouse table coordinate."""

    catalog: str
    schema: str
    table: str


@dataclass(frozen=True)
class TableNamespace:
    """Default qualifiers for a partially qualified table reference."""

    catalog: str
    schema: str | None = None


@dataclass(frozen=True)
class EligibleTableScopeColumn:
    """A cached column that can carry a row-scope rule."""

    name: str
    column_type: TableScopeColumnType


@dataclass(frozen=True)
class TableScopeRule:
    """A validated rule consumed by the pure rewrite engine."""

    table: TableCoordinate
    column_name: str
    column_type: TableScopeColumnType
    allowed_values: tuple[str, ...]


@dataclass(frozen=True)
class TableScopeQueryParameter:
    """One provider-owned bound-parameter payload emitted by a rewrite."""

    name: str
    payload: dict[str, object]


@dataclass(frozen=True)
class TableScopeRewriteResult:
    """A rewritten query plus its parameters and resolved table references."""

    query: str
    parameters: tuple[TableScopeQueryParameter, ...]
    referenced_tables: frozenset[TableCoordinate]


class TableScopeRewriteError(ValueError):
    """The query cannot be safely rewritten under active row-scope rules."""
