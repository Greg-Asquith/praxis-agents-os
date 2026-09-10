// apps/web/src/integrations/google_analytics/lib/tool-details.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import {
  formatDateRange,
  formatFilterSummary,
  metricLabel,
} from "@/integrations/google_analytics/lib/report-model"
import {
  booleanArg,
  compactDetails,
  listDetail,
  numberDetail,
  stringArg,
  stringDetail,
} from "@/integrations/tool-details"
import { titleCaseToken } from "@/lib/format"
import { isRecord } from "@/lib/guards"

export function reportDetails(args: unknown): FanOutDetail[] {
  return commonReportDetails(args, dateRanges(args))
}

export function realtimeDetails(args: unknown): FanOutDetail[] {
  return commonReportDetails(args, minuteRanges(args))
}

export function reportFieldsDetails(args: unknown): FanOutDetail[] {
  const kind = stringArg(args, "kind")
  return compactDetails([
    stringDetail(args, "search", "Search"),
    kind ? { label: "Field type", value: titleCaseToken(kind, kind) } : null,
    booleanArg(args, "custom_only") === true ? { label: "Fields", value: "Custom only" } : null,
    numberDetail(args, "limit", "Limit"),
  ])
}

export function compatibilityDetails(args: unknown): FanOutDetail[] {
  return compactDetails([
    listDetail(args, "metrics", "Current metrics"),
    listDetail(args, "dimensions", "Current dimensions"),
    listDetail(args, "candidate_metrics", "Candidate metrics"),
    listDetail(args, "candidate_dimensions", "Candidate dimensions"),
    filterDetail(args),
  ])
}

function commonReportDetails(args: unknown, ranges: string[]): FanOutDetail[] {
  const order = isRecord(args) ? orderSummary(args["order_bys"]) : null
  return compactDetails([
    listDetail(args, "metrics", "Metrics", metricLabel),
    listDetail(args, "dimensions", "Dimensions", metricLabel),
    ranges.length > 0 ? { label: "Range", value: ranges.join("; ") } : null,
    filterDetail(args),
    order ? { label: "Order", value: order } : null,
    numberDetail(args, "limit", "Limit"),
  ])
}

function filterDetail(args: unknown): FanOutDetail | null {
  if (!isRecord(args)) return null
  const values: string[] = []
  for (const filters of [args["dimension_filter"], args["metric_filter"]]) {
    if (!Array.isArray(filters)) continue
    for (const filter of filters) {
      const summary = formatFilterSummary(filter)
      if (summary) values.push(summary)
    }
  }
  return values.length > 0 ? { label: "Filters", summary: false, value: values.join("; ") } : null
}

function dateRanges(args: unknown): string[] {
  return isRecord(args) && Array.isArray(args["date_ranges"])
    ? args["date_ranges"].flatMap((value) => formatDateRange(value) ?? [])
    : []
}

function minuteRanges(args: unknown): string[] {
  const ranges = isRecord(args) ? args["minute_ranges"] : undefined
  if (!Array.isArray(ranges) || ranges.length === 0) {
    return ["Last 30 minutes"]
  }
  return ranges.flatMap((value) => {
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
    const field = stringArg(item, "metric") ?? stringArg(item, "dimension")
    return field && isRecord(item)
      ? `by ${metricLabel(field)}, ${item["desc"] === true ? "desc" : "asc"}`
      : []
  })
  return summaries.length > 0 ? summaries.join("; ") : null
}
