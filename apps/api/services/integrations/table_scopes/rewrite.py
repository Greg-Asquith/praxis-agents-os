# apps/api/services/integrations/table_scopes/rewrite.py

"""Parse and rewrite governed warehouse table references."""

from collections.abc import Mapping

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.scope import Scope, traverse_scope

from .adapter import TableScopeAdapter
from .domain import (
    TableCoordinate,
    TableNamespace,
    TableScopeQueryParameter,
    TableScopeRewriteError,
    TableScopeRewriteResult,
    TableScopeRule,
)

_RESERVED_PARAMETER_PREFIX = "praxis_scope_"


def rewrite_table_scopes(
    query: str,
    *,
    default_namespace: TableNamespace,
    rules: Mapping[TableCoordinate, TableScopeRule],
    adapter: TableScopeAdapter,
) -> TableScopeRewriteResult:
    """Applies every matching rule and rejects references that cannot be resolved."""
    try:
        statements = sqlglot.parse(query, read=adapter.dialect)
    except (SqlglotError, ValueError) as exc:
        raise TableScopeRewriteError(
            "The query could not be parsed while row filters are active. Revise the query."
        ) from exc
    if len(statements) != 1 or statements[0] is None:
        raise TableScopeRewriteError("Row-filtered queries must contain exactly one SQL statement.")
    statement = statements[0]
    if any(
        parameter.name.lower().startswith(_RESERVED_PARAMETER_PREFIX)
        for parameter in statement.find_all(exp.Parameter)
    ):
        raise TableScopeRewriteError(
            "Query parameter names beginning with praxis_scope_ are reserved for row filters."
        )

    referenced_tables: set[TableCoordinate] = set()
    governed_nodes: list[tuple[exp.Table, TableScopeRule]] = []
    for table in _physical_tables(statement):
        coordinate = _resolve_coordinate(table, default_namespace=default_namespace)
        if "*" in coordinate.table:
            raise TableScopeRewriteError(
                "Wildcard table references are unavailable while row filters are active."
            )
        if adapter.should_skip_reference(coordinate):
            continue
        referenced_tables.add(coordinate)
        rule = rules.get(coordinate)
        if rule is not None:
            if rule.table != coordinate:
                raise TableScopeRewriteError(
                    "A row-filter rule has inconsistent table coordinates."
                )
            if not rule.allowed_values:
                raise TableScopeRewriteError("A row-filter rule must contain at least one value.")
            adapter.validate_governed_table(table)
            governed_nodes.append((table, rule))

    parameter_by_rule: dict[TableScopeRule, TableScopeQueryParameter] = {}
    for table, rule in governed_nodes:
        parameter = parameter_by_rule.get(rule)
        if parameter is None:
            name = f"{_RESERVED_PARAMETER_PREFIX}{len(parameter_by_rule)}"
            parameter = adapter.query_parameter(
                name=name,
                column_type=rule.column_type,
                values=rule.allowed_values,
            )
            if parameter.name != name:
                raise TableScopeRewriteError(
                    "The table-scope adapter returned an inconsistent parameter name."
                )
            parameter_by_rule[rule] = parameter
        predicate = adapter.membership_predicate(
            column_name=rule.column_name,
            parameter_name=parameter.name,
        )
        _wrap_table(table, predicate=predicate)

    return TableScopeRewriteResult(
        query=statement.sql(dialect=adapter.dialect),
        parameters=tuple(parameter_by_rule.values()),
        referenced_tables=frozenset(referenced_tables),
    )


def _physical_tables(statement: exp.Expression) -> list[exp.Table]:
    tables: list[exp.Table] = []
    seen: set[int] = set()
    for scope in traverse_scope(statement):
        _append_physical_scope_tables(scope, tables=tables, seen=seen)
    return tables


def _append_physical_scope_tables(
    scope: Scope,
    *,
    tables: list[exp.Table],
    seen: set[int],
) -> None:
    for table in scope.tables:
        source = scope.sources.get(table.alias_or_name)
        identity = id(table)
        if not isinstance(source, Scope) and identity not in seen:
            seen.add(identity)
            tables.append(table)


def _resolve_coordinate(
    table: exp.Table,
    *,
    default_namespace: TableNamespace,
) -> TableCoordinate:
    table_name = table.name.strip()
    schema = table.db.strip() or (default_namespace.schema or "").strip()
    catalog = table.catalog.strip() or default_namespace.catalog.strip()
    if not table_name or not schema or not catalog:
        raise TableScopeRewriteError(
            "Every table must include enough qualifiers to resolve a full table name "
            "while row filters are active."
        )
    return TableCoordinate(catalog=catalog, schema=schema, table=table_name)


def _wrap_table(table: exp.Table, *, predicate: exp.Expression) -> None:
    alias = table.args.get("alias")
    table_alias = (
        alias.copy()
        if isinstance(alias, exp.TableAlias)
        else exp.TableAlias(this=table.this.copy())
    )
    base_table = table.copy()
    base_table.set("alias", None)
    base_table.set("pivots", None)
    filtered = exp.select("*").from_(base_table).where(predicate).subquery(alias=table_alias)
    table.replace(filtered)
