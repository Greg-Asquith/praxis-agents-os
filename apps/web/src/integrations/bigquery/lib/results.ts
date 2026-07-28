// apps/web/src/integrations/bigquery/lib/results.ts

import type { DataColumn, DataRow } from "@/components/ui/data-table"
import { titleCaseToken } from "@/lib/format"
import { isRecord } from "@/lib/guards"

type BigQueryTable = {
  description: string | null
  lastSyncedAt: string
  rowCount: number | null
  table: string
  tableType: string
}

export type BigQueryDataset = {
  dataset: string
  displayName: string
  tables: BigQueryTable[]
}

type BigQueryField = {
  description: string | null
  mode: string
  name: string
  type: string
}

export type BigQuerySchema = {
  clusteringFields: string[]
  description: string | null
  fields: BigQueryField[]
  lastSyncedAt: string
  requiresPartitionFilter: boolean
  rowCount: number | null
  sizeBytes: number | null
  table: string
  tableType: string
}

export type BigQueryQueryResult = {
  cacheHit: boolean
  columns: DataColumn[]
  rows: DataRow[]
  totalBytesProcessed: number
  totalRows: number
  truncated: boolean
}

export function bigQueryDatasets(value: unknown): BigQueryDataset[] | null {
  if (!isRecord(value) || !Array.isArray(value["datasets"])) {
    return null
  }
  const datasets: BigQueryDataset[] = []
  for (const item of value["datasets"]) {
    if (
      !isRecord(item) ||
      typeof item["dataset"] !== "string" ||
      typeof item["display_name"] !== "string" ||
      !Array.isArray(item["tables"])
    ) {
      return null
    }
    const tables: BigQueryTable[] = []
    for (const rawTable of item["tables"]) {
      if (
        !isRecord(rawTable) ||
        typeof rawTable["table"] !== "string" ||
        typeof rawTable["table_type"] !== "string" ||
        typeof rawTable["last_synced_at"] !== "string" ||
        !nullableString(rawTable["description"]) ||
        !nullableNumber(rawTable["row_count"])
      ) {
        return null
      }
      tables.push({
        description: rawTable["description"] ?? null,
        lastSyncedAt: rawTable["last_synced_at"],
        rowCount: rawTable["row_count"] ?? null,
        table: rawTable["table"],
        tableType: rawTable["table_type"],
      })
    }
    datasets.push({
      dataset: item["dataset"],
      displayName: item["display_name"],
      tables,
    })
  }
  return datasets
}

export function bigQuerySchema(value: unknown): BigQuerySchema | null {
  if (
    !isRecord(value) ||
    typeof value["table"] !== "string" ||
    typeof value["table_type"] !== "string" ||
    typeof value["last_synced_at"] !== "string" ||
    typeof value["requires_partition_filter"] !== "boolean" ||
    !nullableString(value["description"]) ||
    !nullableNumber(value["row_count"]) ||
    !nullableNumber(value["size_bytes"]) ||
    !Array.isArray(value["clustering_fields"]) ||
    !value["clustering_fields"].every((item): item is string => typeof item === "string") ||
    !Array.isArray(value["fields"])
  ) {
    return null
  }
  const fields: BigQueryField[] = []
  for (const rawField of value["fields"]) {
    if (
      !isRecord(rawField) ||
      typeof rawField["name"] !== "string" ||
      typeof rawField["type"] !== "string" ||
      typeof rawField["mode"] !== "string" ||
      !nullableString(rawField["description"])
    ) {
      return null
    }
    fields.push({
      description: rawField["description"] ?? null,
      mode: rawField["mode"],
      name: rawField["name"],
      type: rawField["type"],
    })
  }
  return {
    clusteringFields: value["clustering_fields"],
    description: value["description"] ?? null,
    fields,
    lastSyncedAt: value["last_synced_at"],
    requiresPartitionFilter: value["requires_partition_filter"],
    rowCount: value["row_count"] ?? null,
    sizeBytes: value["size_bytes"] ?? null,
    table: value["table"],
    tableType: value["table_type"],
  }
}

export function bigQueryQueryResult(value: unknown): BigQueryQueryResult | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value["rows"]) ||
    typeof value["total_rows"] !== "number" ||
    typeof value["truncated"] !== "boolean" ||
    typeof value["total_bytes_processed"] !== "number" ||
    typeof value["cache_hit"] !== "boolean"
  ) {
    return null
  }
  const rows: DataRow[] = []
  const keys: string[] = []
  const seen = new Set<string>()
  for (const rawRow of value["rows"]) {
    if (!isRecord(rawRow)) {
      return null
    }
    const row: DataRow = {}
    for (const [key, cell] of Object.entries(rawRow)) {
      if (cell !== null && typeof cell !== "string") {
        return null
      }
      if (!seen.has(key)) {
        seen.add(key)
        keys.push(key)
      }
      row[key] = cell
    }
    rows.push(row)
  }
  return {
    cacheHit: value["cache_hit"],
    columns: keys.map((key) => ({
      key,
      kind: "text",
      label: titleCaseToken(key, key),
    })),
    rows,
    totalBytesProcessed: value["total_bytes_processed"],
    totalRows: value["total_rows"],
    truncated: value["truncated"],
  }
}

function nullableString(value: unknown): value is string | null | undefined {
  return value === null || value === undefined || typeof value === "string"
}

function nullableNumber(value: unknown): value is number | null | undefined {
  return value === null || value === undefined || typeof value === "number"
}
