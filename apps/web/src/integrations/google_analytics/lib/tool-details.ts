// apps/web/src/integrations/google_analytics/lib/tool-details.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import {
  formatDateRange,
  formatFilterSummary,
  metricLabel,
} from "@/integrations/google_analytics/lib/report-model"
import { titleCaseToken } from "@/lib/format"
import { isRecord } from "@/lib/guards"

export function reportDetails(args: unknown): FanOutDetail[] {
  if (!isRecord(args)) return []
  return commonReportDetails(args, dateRanges(args))
}

export function realtimeDetails(args: unknown): FanOutDetail[] {
  if (!isRecord(args)) return []
  return commonReportDetails(args, minuteRanges(args))
}

export function reportFieldsDetails(args: unknown): FanOutDetail[] {
  if (!isRecord(args)) return []
  const search = stringArg(args, "search")
  const kind = stringArg(args, "kind")
  return [
    ...(search ? [{ label: "Search", value: search }] : []),
    ...(kind ? [{ label: "Field type", value: titleCaseToken(kind, kind) }] : []),
    ...(args["custom_only"] === true ? [{ label: "Fields", value: "Custom only" }] : []),
    ...numberDetail(args, "limit", "Limit"),
  ]
}

export function compatibilityDetails(args: unknown): FanOutDetail[] {
  if (!isRecord(args)) return []
  return [
    ...listDetail(args, "metrics", "Current metrics"),
    ...listDetail(args, "dimensions", "Current dimensions"),
    ...listDetail(args, "candidate_metrics", "Candidate metrics"),
    ...listDetail(args, "candidate_dimensions", "Candidate dimensions"),
    ...filterDetails(args),
  ]
}

function commonReportDetails(args: Record<string, unknown>, ranges: string[]): FanOutDetail[] {
  const order = orderSummary(args["order_bys"])
  return [
    ...listDetail(args, "metrics", "Metrics", metricLabel),
    ...listDetail(args, "dimensions", "Dimensions", metricLabel),
    ...(ranges.length > 0 ? [{ label: "Range", value: ranges.join("; ") }] : []),
    ...filterDetails(args),
    ...(order ? [{ label: "Order", value: order }] : []),
    ...numberDetail(args, "limit", "Limit"),
  ]
}

function filterDetails(args: Record<string, unknown>): FanOutDetail[] {
  const values: string[] = []
  for (const filters of [args["dimension_filter"], args["metric_filter"]]) {
    if (!Array.isArray(filters)) continue
    for (const filter of filters) {
      const summary = formatFilterSummary(filter)
      if (summary) values.push(summary)
    }
  }
  return values.length > 0 ? [{ label: "Filters", summary: false, value: values.join("; ") }] : []
}

function dateRanges(args: Record<string, unknown>): string[] {
  return Array.isArray(args["date_ranges"])
    ? args["date_ranges"].flatMap((value) => formatDateRange(value) ?? [])
    : []
}

function minuteRanges(args: Record<string, unknown>): string[] {
  if (!Array.isArray(args["minute_ranges"]) || args["minute_ranges"].length === 0) {
    return ["Last 30 minutes"]
  }
  return args["minute_ranges"].flatMap((value) => {
    if (
      !isRecord(value) ||
      typeof value["start_minutes_ago"] !== "number" ||
      typeof value["end_minutes_ago"] !== "number"
    )
      return []
    const name = stringArg(value, "name")
    return `${name ? `${name}: ` : ""}${String(value["start_minutes_ago"])} → ${String(value["end_minutes_ago"])} minutes ago`
  })
}

function orderSummary(value: unknown): string | null {
  if (!Array.isArray(value)) return null
  const summaries = value.flatMap((item) => {
    if (!isRecord(item)) return []
    const field = stringArg(item, "metric") ?? stringArg(item, "dimension")
    return field ? `by ${metricLabel(field)}, ${item["desc"] === true ? "desc" : "asc"}` : []
  })
  return summaries.length > 0 ? summaries.join("; ") : null
}

function listDetail(
  args: Record<string, unknown>,
  key: string,
  label: string,
  format: (value: string) => string = (value) => value
): FanOutDetail[] {
  const value = args[key]
  if (
    !Array.isArray(value) ||
    !value.every((item): item is string => typeof item === "string") ||
    value.length === 0
  )
    return []
  return [{ label, value: value.map(format).join(", ") }]
}

function numberDetail(args: Record<string, unknown>, key: string, label: string): FanOutDetail[] {
  return typeof args[key] === "number" ? [{ label, value: String(args[key]) }] : []
}

function stringArg(args: Record<string, unknown>, key: string): string | null {
  return typeof args[key] === "string" && args[key].trim() ? args[key].trim() : null
}
