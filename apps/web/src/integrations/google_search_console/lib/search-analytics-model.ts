// apps/web/src/integrations/google_search_console/lib/search-analytics-model.ts

import { isUntrustedNode } from "@/components/tool-ui/untrusted-node"
import type { DataColumn, DataRow } from "@/components/ui/data-table-model"
import { titleCaseToken } from "@/lib/format"
import { isRecord } from "@/lib/guards"

const METRIC_COLUMNS: DataColumn[] = [
  { key: "clicks", kind: "number", label: "Clicks", isMetric: true },
  { key: "impressions", kind: "number", label: "Impressions", isMetric: true },
  { key: "ctr", kind: "percent", label: "CTR", isMetric: true },
  { key: "position", kind: "number", label: "Position", isMetric: true },
]
const METRIC_KEYS = new Set(METRIC_COLUMNS.map((column) => column.key))

export type SearchAnalyticsReport = {
  columns: DataColumn[]
  rows: DataRow[]
  truncated: boolean
  truncationNote: string | null
}

export function parseSearchAnalyticsData(value: unknown): SearchAnalyticsReport | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value["rows"]) ||
    typeof value["truncated"] !== "boolean" ||
    (value["truncation_note"] !== null && typeof value["truncation_note"] !== "string")
  ) {
    return null
  }
  const rows = parseRows(value["rows"])
  if (!rows) return null
  const dimensionKeys =
    rows.length > 0 ? Object.keys(rows[0] ?? {}).filter((key) => !METRIC_KEYS.has(key)) : []
  if (
    rows.some((row) => {
      const keys = Object.keys(row).filter((key) => !METRIC_KEYS.has(key))
      return keys.length !== dimensionKeys.length || dimensionKeys.some((key) => !(key in row))
    })
  )
    return null
  return {
    columns: [
      ...dimensionKeys.map((key): DataColumn => ({
        key,
        kind: key === "date" ? "date" : key === "page" ? "link" : "text",
        label: titleCaseToken(key.replace(/([a-z])([A-Z])/g, "$1 $2"), key),
      })),
      ...METRIC_COLUMNS,
    ],
    rows,
    truncated: value["truncated"],
    truncationNote: value["truncation_note"],
  }
}

function parseRows(values: unknown[]): DataRow[] | null {
  const rows: DataRow[] = []
  for (const value of values) {
    if (
      !isRecord(value) ||
      !isRecord(value["keys"]) ||
      typeof value["clicks"] !== "number" ||
      typeof value["impressions"] !== "number" ||
      typeof value["ctr"] !== "number" ||
      typeof value["position"] !== "number"
    ) {
      return null
    }
    const keys: DataRow = {}
    for (const [key, item] of Object.entries(value["keys"])) {
      if (typeof item !== "string" && !isUntrustedNode(item)) return null
      keys[key] = item
    }
    rows.push({
      ...keys,
      clicks: value["clicks"],
      ctr: value["ctr"],
      impressions: value["impressions"],
      position: value["position"],
    })
  }
  return rows
}
