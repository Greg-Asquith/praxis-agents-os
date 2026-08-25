# apps/api/integrations/bigquery/operations/scope_rewrite.py

"""BigQuery adapter for provider-neutral table row-scope rewriting."""

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from services.integrations.table_scopes.domain import (
    EligibleTableScopeColumn,
    TableCoordinate,
    TableScopeColumnType,
    TableScopeQueryParameter,
    TableScopeRewriteError,
)

if TYPE_CHECKING:
    from sqlglot import exp

_ELIGIBLE_TYPES: dict[str, TableScopeColumnType] = {
    "STRING": "string",
    "INT64": "integer",
    "INTEGER": "integer",
}


class BigQueryTableScopeAdapter:
    """Emits GoogleSQL predicates and BigQuery REST parameter payloads."""

    dialect = "bigquery"

    def eligible_columns(
        self,
        schema_fields: Sequence[Mapping[str, object]],
    ) -> tuple[EligibleTableScopeColumn, ...]:
        eligible: list[EligibleTableScopeColumn] = []
        for field in schema_fields:
            name = str(field.get("name", "")).strip()
            provider_type = str(field.get("type", "")).strip().upper()
            mode = str(field.get("mode", "NULLABLE")).strip().upper() or "NULLABLE"
            column_type = _ELIGIBLE_TYPES.get(provider_type)
            if name and "." not in name and mode != "REPEATED" and column_type is not None:
                eligible.append(EligibleTableScopeColumn(name=name, column_type=column_type))
        return tuple(eligible)

    def should_skip_reference(self, table: TableCoordinate) -> bool:
        parts = (table.catalog.upper(), table.schema.upper(), table.table.upper())
        return any(
            part == "INFORMATION_SCHEMA" or part.startswith("INFORMATION_SCHEMA.") for part in parts
        )

    def validate_governed_table(self, table: "exp.Table") -> None:
        if table.args.get("version") is not None:
            raise TableScopeRewriteError(
                "FOR SYSTEM_TIME AS OF is unavailable on row-filtered tables."
            )
        if table.args.get("pivots"):
            raise TableScopeRewriteError(
                "PIVOT and UNPIVOT are unavailable directly on row-filtered tables. "
                "Filter the table in a subquery before applying the operation."
            )

    def membership_predicate(
        self,
        *,
        column_name: str,
        parameter_name: str,
    ) -> "exp.Expression":
        from sqlglot import exp

        return exp.In(
            this=exp.column(column_name, quoted=True),
            unnest=exp.Unnest(
                expressions=[exp.Parameter(this=exp.Var(this=parameter_name))],
            ),
        )

    def query_parameter(
        self,
        *,
        name: str,
        column_type: TableScopeColumnType,
        values: tuple[str, ...],
    ) -> TableScopeQueryParameter:
        provider_type = "STRING" if column_type == "string" else "INT64"
        return TableScopeQueryParameter(
            name=name,
            payload={
                "name": name,
                "parameterType": {
                    "type": "ARRAY",
                    "arrayType": {"type": provider_type},
                },
                "parameterValue": {
                    "arrayValues": [{"value": value} for value in values],
                },
            },
        )


BIGQUERY_TABLE_SCOPE_ADAPTER = BigQueryTableScopeAdapter()
