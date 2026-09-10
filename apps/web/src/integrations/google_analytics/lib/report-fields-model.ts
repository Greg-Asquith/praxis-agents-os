// apps/web/src/integrations/google_analytics/lib/report-fields-model.ts

import type { DataRow } from "@/components/ui/data-table"
import { isNonNegativeInteger, isRecord } from "@/lib/guards"

export type GoogleAnalyticsReportFields = {
  dimensionCount: number
  dimensions: DataRow[]
  metricCount: number
  metrics: DataRow[]
  truncated: boolean
}

export function parseReportFields(value: unknown): GoogleAnalyticsReportFields | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value["dimensions"]) ||
    !Array.isArray(value["metrics"]) ||
    !isNonNegativeInteger(value["dimension_count"]) ||
    !isNonNegativeInteger(value["metric_count"]) ||
    typeof value["truncated"] !== "boolean"
  )
    return null
  const dimensions = parseFields(value["dimensions"], false)
  const metrics = parseFields(value["metrics"], true)
  if (!dimensions || !metrics) return null
  return {
    dimensionCount: value["dimension_count"],
    dimensions,
    metricCount: value["metric_count"],
    metrics,
    truncated: value["truncated"],
  }
}

function parseFields(values: unknown[], metric: boolean): DataRow[] | null {
  const rows: DataRow[] = []
  for (const value of values) {
    const blockedReasons = isRecord(value) ? value["blocked_reasons"] : null
    if (
      !isRecord(value) ||
      typeof value["api_name"] !== "string" ||
      typeof value["ui_name"] !== "string" ||
      typeof value["category"] !== "string" ||
      typeof value["description"] !== "string" ||
      typeof value["custom"] !== "boolean" ||
      (metric && (typeof value["type"] !== "string" || !Array.isArray(blockedReasons)))
    )
      return null
    if (
      metric &&
      Array.isArray(blockedReasons) &&
      !blockedReasons.every((item) => typeof item === "string")
    )
      return null
    rows.push({
      api_name: value["api_name"],
      category: value["category"],
      custom: value["custom"] ? "Custom" : "Standard",
      ui_name: value["ui_name"],
    })
  }
  return rows
}
