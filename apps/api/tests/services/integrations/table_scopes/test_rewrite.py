"""Provider-neutral table row-scope rewrite behavior."""

import pytest

from integrations.bigquery.operations.scope_rewrite import BIGQUERY_TABLE_SCOPE_ADAPTER
from services.integrations.table_scopes.domain import (
    TableCoordinate,
    TableNamespace,
    TableScopeRewriteError,
    TableScopeRule,
)
from services.integrations.table_scopes.rewrite import rewrite_table_scopes

GOOGLE_ADS = TableCoordinate("billing-project", "marketing", "google_ads")
GOOGLE_ADS_RULE = TableScopeRule(
    table=GOOGLE_ADS,
    column_name="account_id",
    column_type="string",
    allowed_values=("123", "456"),
)


def _rewrite(query: str, *rules: TableScopeRule):
    return rewrite_table_scopes(
        query,
        default_namespace=TableNamespace(catalog="billing-project"),
        rules={rule.table: rule for rule in rules},
        adapter=BIGQUERY_TABLE_SCOPE_ADAPTER,
    )


def test_rewrite_wraps_before_the_outer_where_expression() -> None:
    result = _rewrite(
        "SELECT * FROM `billing-project.marketing.google_ads` "
        "WHERE campaign_status = 'ENABLED' OR clicks > 0",
        GOOGLE_ADS_RULE,
    )

    assert result.query == (
        "SELECT * FROM (SELECT * FROM `billing-project.marketing.google_ads` "
        "WHERE `account_id` IN UNNEST(@praxis_scope_0)) AS `google_ads` "
        "WHERE campaign_status = 'ENABLED' OR clicks > 0"
    )


@pytest.mark.parametrize(
    ("query", "wrapper_count"),
    [
        (
            "WITH scoped AS (SELECT * FROM `billing-project.marketing.google_ads`) "
            "SELECT * FROM scoped",
            1,
        ),
        (
            "SELECT * FROM (SELECT * FROM `billing-project.marketing.google_ads`) nested",
            1,
        ),
        (
            "SELECT a.account_id FROM `billing-project.marketing.google_ads` a "
            "JOIN `billing-project.marketing.google_ads` b USING (account_id)",
            2,
        ),
        (
            "SELECT * FROM `billing-project.marketing.google_ads` UNION ALL "
            "SELECT * FROM `billing-project.marketing.google_ads`",
            2,
        ),
    ],
)
def test_rewrite_wraps_every_physical_table_occurrence(
    query: str,
    wrapper_count: int,
) -> None:
    result = _rewrite(query, GOOGLE_ADS_RULE)

    assert result.query.count("IN UNNEST(@praxis_scope_0)") == wrapper_count
    assert len(result.parameters) == 1


def test_rewrite_preserves_explicit_and_implicit_aliases() -> None:
    explicit = _rewrite(
        "SELECT ads.account_id FROM `billing-project.marketing.google_ads` ads",
        GOOGLE_ADS_RULE,
    )
    implicit = _rewrite(
        "SELECT google_ads.account_id FROM `billing-project.marketing.google_ads`",
        GOOGLE_ADS_RULE,
    )

    assert ") AS ads" in explicit.query
    assert ") AS `google_ads`" in implicit.query


def test_rewrite_resolves_dataset_table_against_the_default_catalog() -> None:
    other_project = TableCoordinate("other-project", "marketing", "google_ads")
    result = _rewrite(
        "SELECT * FROM marketing.google_ads UNION ALL "
        "SELECT * FROM `other-project.marketing.google_ads`",
        GOOGLE_ADS_RULE,
    )

    assert result.query.count("IN UNNEST(@praxis_scope_0)") == 1
    assert result.referenced_tables == frozenset({GOOGLE_ADS, other_project})


def test_rewrite_leaves_ungoverned_tables_unwrapped() -> None:
    ungoverned = TableCoordinate("billing-project", "marketing", "campaigns")
    result = _rewrite(
        "SELECT * FROM `billing-project.marketing.campaigns`",
        GOOGLE_ADS_RULE,
    )

    assert result.query == "SELECT * FROM `billing-project.marketing.campaigns`"
    assert result.parameters == ()
    assert result.referenced_tables == frozenset({ungoverned})


def test_rewrite_emits_distinct_typed_parameters_per_rule() -> None:
    accounts = TableCoordinate("billing-project", "marketing", "accounts")
    integer_rule = TableScopeRule(
        table=accounts,
        column_name="customer_id",
        column_type="integer",
        allowed_values=("789",),
    )
    result = _rewrite(
        "SELECT * FROM `billing-project.marketing.google_ads` UNION ALL "
        "SELECT * FROM `billing-project.marketing.accounts`",
        GOOGLE_ADS_RULE,
        integer_rule,
    )

    assert [parameter.payload for parameter in result.parameters] == [
        {
            "name": "praxis_scope_0",
            "parameterType": {"type": "ARRAY", "arrayType": {"type": "STRING"}},
            "parameterValue": {"arrayValues": [{"value": "123"}, {"value": "456"}]},
        },
        {
            "name": "praxis_scope_1",
            "parameterType": {"type": "ARRAY", "arrayType": {"type": "INT64"}},
            "parameterValue": {"arrayValues": [{"value": "789"}]},
        },
    ]


@pytest.mark.parametrize(
    ("query", "message"),
    [
        ("SELECT * FROM (", "could not be parsed"),
        ("SELECT 1; SELECT 2", "exactly one"),
        (
            "SELECT * FROM `billing-project.marketing.google_ads_*`",
            "Wildcard table references",
        ),
        (
            "SELECT * FROM `billing-project.marketing.google_ads` "
            "FOR SYSTEM_TIME AS OF TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)",
            "FOR SYSTEM_TIME AS OF",
        ),
        (
            "SELECT * FROM `billing-project.marketing.google_ads` "
            "PIVOT(SUM(clicks) FOR status IN ('enabled'))",
            "PIVOT and UNPIVOT",
        ),
        ("SELECT @praxis_scope_existing", "parameter names"),
        ("SELECT * FROM google_ads", "enough qualifiers"),
    ],
)
def test_rewrite_rejects_unsafe_or_unresolvable_queries(query: str, message: str) -> None:
    with pytest.raises(TableScopeRewriteError, match=message):
        _rewrite(query, GOOGLE_ADS_RULE)


def test_rewrite_skips_information_schema_references() -> None:
    result = _rewrite(
        "SELECT * FROM `billing-project.marketing.INFORMATION_SCHEMA.TABLES`",
        GOOGLE_ADS_RULE,
    )

    assert result.parameters == ()
    assert result.referenced_tables == frozenset()
