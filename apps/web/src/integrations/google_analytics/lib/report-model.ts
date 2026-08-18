// apps/web/src/integrations/google_analytics/lib/report-model.ts

import type { DataColumn, DataColumnKind, DataRow } from "@/components/ui/data-table"
import { titleCaseToken } from "@/lib/format"
import { isRecord } from "@/lib/guards"

export type GoogleAnalyticsMetricHeader = {
  name: string
  type: string
}

type GoogleAnalyticsReportMetadata = {
  currencyCode: string
  dataLossFromOtherRow: boolean
  sampled: boolean
  samplingNotes: string[]
  thresholded: boolean
}

export type GoogleAnalyticsReport = {
  columns: DataColumn[]
  maximums: DataRow[]
  metadata: GoogleAnalyticsReportMetadata
  minimums: DataRow[]
  rowCount: number
  rows: DataRow[]
  totals: DataRow[]
  truncated: boolean
  truncationNote: string | null
}

const DATE_DIMENSIONS = new Set(["date", "firstSessionDate"])
const COMMON_METRIC_LABELS: Record<string, string> = {
  activeUsers: "Active users",
  eventCount: "Event count",
  keyEvents: "Key events",
  screenPageViews: "Views",
  sessions: "Sessions",
  totalUsers: "Total users",
}

export function parseReportData(value: unknown): GoogleAnalyticsReport | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value["rows"]) ||
    !Array.isArray(value["totals"]) ||
    !Array.isArray(value["maximums"]) ||
    !Array.isArray(value["minimums"]) ||
    !Array.isArray(value["dimension_headers"]) ||
    !Array.isArray(value["metric_headers"]) ||
    typeof value["row_count"] !== "number" ||
    !Number.isInteger(value["row_count"]) ||
    value["row_count"] < 0 ||
    typeof value["truncated"] !== "boolean" ||
    (value["truncation_note"] !== null && typeof value["truncation_note"] !== "string")
  ) {
    return null
  }
  const dimensionHeaders = stringList(value["dimension_headers"])
  const metricHeaders = parseMetricHeaders(value["metric_headers"])
  const metadata = parseMetadata(value["metadata"])
  if (!dimensionHeaders || !metricHeaders || !metadata) {
    return null
  }
  const rows = parseRows(value["rows"], dimensionHeaders, metricHeaders)
  const totals = parseRows(value["totals"], dimensionHeaders, metricHeaders)
  const maximums = parseRows(value["maximums"], dimensionHeaders, metricHeaders)
  const minimums = parseRows(value["minimums"], dimensionHeaders, metricHeaders)
  if (!rows || !totals || !maximums || !minimums) {
    return null
  }
  return {
    columns: columnsFromHeaders(dimensionHeaders, metricHeaders, metadata.currencyCode),
    maximums,
    metadata,
    minimums,
    rowCount: value["row_count"],
    rows,
    totals,
    truncated: value["truncated"],
    truncationNote: value["truncation_note"],
  }
}

export function columnsFromHeaders(
  dimensionHeaders: string[],
  metricHeaders: GoogleAnalyticsMetricHeader[],
  currencyCode: string
): DataColumn[] {
  return [
    ...dimensionHeaders.map((name): DataColumn => ({
      key: name,
      kind: dimensionKind(name),
      label: fieldLabel(name),
    })),
    ...metricHeaders.map((header): DataColumn => {
      const kind = metricKind(header)
      return {
        key: header.name,
        kind,
        label: metricLabel(header.name),
        isMetric: kind === "number" || kind === "currency" || kind === "percent",
        ...(header.type === "TYPE_MILLISECONDS" ? { unit: "milliseconds" as const } : {}),
        ...(header.type === "TYPE_SECONDS" ? { unit: "seconds" as const } : {}),
        ...(kind === "currency" && currencyCode ? { currencyCode } : {}),
      }
    }),
  ]
}

export function metricLabel(name: string): string {
  return COMMON_METRIC_LABELS[name] ?? fieldLabel(name)
}

export function formatDateToken(value: string): string {
  const match = /^(\d{4})(\d{2})(\d{2})(\d{2})?$/.exec(value)
  if (!match) return value
  const year = match[1]
  const month = match[2]
  const day = match[3]
  const hour = match[4]
  if (!year || !month || !day) return value
  return hour ? `${year}-${month}-${day}T${hour}:00:00` : `${year}-${month}-${day}`
}

export function formatDateRange(value: unknown): string | null {
  if (
    !isRecord(value) ||
    typeof value["start_date"] !== "string" ||
    typeof value["end_date"] !== "string"
  ) {
    return null
  }
  const start = humanizeRelativeDate(value["start_date"])
  const end = humanizeRelativeDate(value["end_date"])
  const name =
    typeof value["name"] === "string" && value["name"].trim() ? value["name"].trim() : null
  return `${name ? `${name}: ` : ""}${start} → ${end}`
}

export function formatFilterSummary(value: unknown): string | null {
  if (!isRecord(value) || typeof value["field_name"] !== "string") {
    return null
  }
  const field = fieldLabel(value["field_name"])
  const prefix = value["negate"] === true ? "not " : ""
  if (isRecord(value["string_filter"])) {
    const filter = value["string_filter"]
    if (typeof filter["value"] !== "string") return null
    const relation = stringRelation(filter["match_type"])
    return `${field} ${prefix}${relation} ${filter["value"]}`
  }
  if (isRecord(value["in_list_filter"]) && Array.isArray(value["in_list_filter"]["values"])) {
    const values = stringList(value["in_list_filter"]["values"])
    return values ? `${field} ${prefix}is one of ${values.join(", ")}` : null
  }
  if (isRecord(value["numeric_filter"]) && typeof value["numeric_filter"]["value"] === "number") {
    return `${field} ${prefix}${numericRelation(value["numeric_filter"]["operation"])} ${String(value["numeric_filter"]["value"])}`
  }
  if (
    isRecord(value["between_filter"]) &&
    typeof value["between_filter"]["from_value"] === "number" &&
    typeof value["between_filter"]["to_value"] === "number"
  ) {
    return `${field} ${prefix}is between ${String(value["between_filter"]["from_value"])} and ${String(value["between_filter"]["to_value"])}`
  }
  return null
}

function parseMetricHeaders(values: unknown[]): GoogleAnalyticsMetricHeader[] | null {
  const headers: GoogleAnalyticsMetricHeader[] = []
  for (const value of values) {
    if (
      !isRecord(value) ||
      typeof value["name"] !== "string" ||
      typeof value["type"] !== "string"
    ) {
      return null
    }
    headers.push({ name: value["name"], type: value["type"] })
  }
  return headers
}

function parseMetadata(value: unknown): GoogleAnalyticsReportMetadata | null {
  if (
    !isRecord(value) ||
    typeof value["currency_code"] !== "string" ||
    typeof value["sampled"] !== "boolean" ||
    !Array.isArray(value["sampling_notes"]) ||
    typeof value["data_loss_from_other_row"] !== "boolean" ||
    typeof value["thresholded"] !== "boolean"
  ) {
    return null
  }
  const samplingNotes = stringList(value["sampling_notes"])
  if (!samplingNotes) return null
  return {
    currencyCode: value["currency_code"],
    dataLossFromOtherRow: value["data_loss_from_other_row"],
    sampled: value["sampled"],
    samplingNotes,
    thresholded: value["thresholded"],
  }
}

function parseRows(
  values: unknown[],
  dimensionHeaders: string[],
  metricHeaders: GoogleAnalyticsMetricHeader[]
): DataRow[] | null {
  const allowed = new Set([...dimensionHeaders, ...metricHeaders.map((header) => header.name)])
  const rows: DataRow[] = []
  for (const value of values) {
    if (!isRecord(value) || Object.keys(value).some((key) => !allowed.has(key))) return null
    const row: DataRow = {}
    for (const [key, item] of Object.entries(value)) {
      if (item !== null && typeof item !== "string" && typeof item !== "number") return null
      if ((DATE_DIMENSIONS.has(key) || key === "dateHour") && typeof item === "string") {
        row[key] = formatDateToken(item)
      } else if (key === "dateRange" && typeof item === "string") {
        row[key] = titleCaseToken(item, item)
      } else {
        row[key] = item
      }
    }
    rows.push(row)
  }
  return rows
}

function dimensionKind(name: string): DataColumnKind {
  if (name === "dateHour") return "datetime"
  if (DATE_DIMENSIONS.has(name)) return "date"
  if (name === "dateRange") return "badge"
  return "text"
}

function metricKind(header: GoogleAnalyticsMetricHeader): DataColumnKind {
  if (isRateMetric(header.name)) return "percent"
  if (header.type === "TYPE_CURRENCY") return "currency"
  return "number"
}

function isRateMetric(name: string): boolean {
  return name === "bounceRate" || name === "engagementRate" || name.endsWith("Rate")
}

function fieldLabel(value: string): string {
  const spaced = value.replace(/([a-z0-9])([A-Z])/g, "$1 $2").replace(/:/g, " ")
  return titleCaseToken(spaced, value)
}

function humanizeRelativeDate(value: string): string {
  const match = /^(\d+)daysAgo$/i.exec(value)
  const days = match?.[1]
  if (days) return `${days} days ago`
  return /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : fieldLabel(value)
}

function stringRelation(value: unknown): string {
  const relations: Record<string, string> = {
    BEGINS_WITH: "starts with",
    CONTAINS: "contains",
    ENDS_WITH: "ends with",
    EXACT: "is",
    FULL_REGEXP: "matches",
    PARTIAL_REGEXP: "matches",
  }
  return typeof value === "string" ? (relations[value] ?? "is") : "is"
}

function numericRelation(value: unknown): string {
  const relations: Record<string, string> = {
    EQUAL: "is",
    GREATER_THAN: ">",
    GREATER_THAN_OR_EQUAL: "≥",
    LESS_THAN: "<",
    LESS_THAN_OR_EQUAL: "≤",
  }
  return typeof value === "string" ? (relations[value] ?? "is") : "is"
}

function stringList(value: unknown[]): string[] | null {
  return value.every((item): item is string => typeof item === "string") ? value : null
}
