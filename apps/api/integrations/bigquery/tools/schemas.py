# apps/api/integrations/bigquery/tools/schemas.py

"""Typed BigQuery tool-result contracts."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BigQueryTableSummary(_StrictModel):
    table: str
    table_type: str
    description: str | None = None
    row_count: int | None = None
    last_synced_at: datetime


class BigQueryDatasetTables(_StrictModel):
    dataset: str
    display_name: str
    tables: list[BigQueryTableSummary]


class BigQueryListTablesOutput(_StrictModel):
    datasets: list[BigQueryDatasetTables]


class BigQuerySchemaField(_StrictModel):
    name: str
    type: str
    mode: str
    description: str | None = None


class BigQueryPartitioning(_StrictModel):
    type: str | None = None
    field: str | None = None
    require_partition_filter: bool = False


class BigQueryTableSchemaOutput(_StrictModel):
    table: str
    table_type: str
    description: str | None = None
    fields: list[BigQuerySchemaField]
    partitioning: BigQueryPartitioning
    clustering_fields: list[str]
    row_count: int | None = None
    size_bytes: int | None = None
    last_synced_at: datetime
    requires_partition_filter: bool


class BigQueryRunQueryOutput(_StrictModel):
    rows: list[dict[str, str | None]]
    total_rows: int
    truncated: bool
    total_bytes_processed: int
    cache_hit: bool
