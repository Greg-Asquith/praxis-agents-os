# apps/api/integrations/bigquery/tools/schemas.py

"""Typed BigQuery tool-result contracts."""

from datetime import datetime

from pydantic import BaseModel


class BigQueryTableSummary(BaseModel):
    table: str
    table_type: str
    description: str | None = None
    row_count: int | None = None
    last_synced_at: datetime


class BigQueryDatasetTables(BaseModel):
    dataset: str
    display_name: str
    tables: list[BigQueryTableSummary]


class BigQueryListTablesOutput(BaseModel):
    datasets: list[BigQueryDatasetTables]


class BigQuerySchemaField(BaseModel):
    name: str
    type: str
    mode: str
    description: str | None = None


class BigQueryTableSchemaOutput(BaseModel):
    table: str
    table_type: str
    description: str | None = None
    fields: list[BigQuerySchemaField]
    partitioning: dict[str, object]
    clustering_fields: list[str]
    row_count: int | None = None
    size_bytes: int | None = None
    last_synced_at: datetime
    requires_partition_filter: bool


class BigQueryRunQueryOutput(BaseModel):
    rows: list[dict[str, str | None]]
    total_rows: int
    truncated: bool
    total_bytes_processed: int
    cache_hit: bool
