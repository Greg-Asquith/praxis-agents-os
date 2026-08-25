"""BigQuery table row-scope adapter behavior."""

import subprocess
import sys

import pytest

from integrations.bigquery.operations.scope_rewrite import BIGQUERY_TABLE_SCOPE_ADAPTER
from services.integrations.table_scopes.domain import (
    EligibleTableScopeColumn,
    TableScopeValueError,
)


def test_adapter_exposes_only_top_level_scalar_string_and_integer_columns() -> None:
    columns = BIGQUERY_TABLE_SCOPE_ADAPTER.eligible_columns(
        [
            {"name": "account_id", "type": "STRING", "mode": "REQUIRED"},
            {"name": "customer_id", "type": "INT64", "mode": "NULLABLE"},
            {"name": "legacy_id", "type": "INTEGER", "mode": "NULLABLE"},
            {"name": "tags", "type": "STRING", "mode": "REPEATED"},
            {"name": "metrics", "type": "RECORD", "mode": "NULLABLE"},
            {"name": "metrics.clicks", "type": "INTEGER", "mode": "NULLABLE"},
            {"name": "spend", "type": "NUMERIC", "mode": "NULLABLE"},
        ]
    )

    assert columns == (
        EligibleTableScopeColumn(name="account_id", column_type="string"),
        EligibleTableScopeColumn(name="customer_id", column_type="integer"),
        EligibleTableScopeColumn(name="legacy_id", column_type="integer"),
    )


def test_adapter_enforces_bigquery_integer_range() -> None:
    BIGQUERY_TABLE_SCOPE_ADAPTER.validate_allowed_values(
        column_type="integer",
        values=("-9223372036854775808", "9223372036854775807"),
    )

    with pytest.raises(TableScopeValueError, match="BigQuery INT64"):
        BIGQUERY_TABLE_SCOPE_ADAPTER.validate_allowed_values(
            column_type="integer",
            values=("9223372036854775808",),
        )


def test_loading_the_bigquery_provider_does_not_import_sqlglot() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import integrations.bigquery; "
            "raise SystemExit(1 if 'sqlglot' in sys.modules else 0)",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
