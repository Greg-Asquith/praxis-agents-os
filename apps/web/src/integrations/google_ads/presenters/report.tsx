// apps/web/src/integrations/google_ads/presenters/report.tsx

import {
  DataTable,
  isMicrosColumnKey,
  type DataColumn,
  type DataColumnKind,
  type DataRow,
} from "@/components/ui/data-table"
import { parseFanOutData } from "@/components/tool-ui/fan-out"
import { FanOutShell, FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import type { ToolRowPresenter } from "@/integrations/contract"
import { googleAdsReportDetails } from "@/integrations/google_ads/lib/tool-details"
import { GoogleAdsToolHeading } from "@/integrations/google_ads/components/tool-heading"
import { formatGoogleAdsAccountId, titleCaseToken } from "@/lib/format"
import { isRecord } from "@/lib/guards"

type GoogleAdsReport = {
  columns: DataColumn[]
  currencyCode: string
  rowCount: number
  rows: DataRow[]
  truncated: boolean
  truncationNote: string | null
}

export const googleAdsReportPresenter: ToolRowPresenter = {
  key: "google-ads-run-report",
  matches: (activity) => activity.name === "google_ads_run_report",
  render: ({ activity, defaultOpen }) => {
    if (activity.status === "running") {
      return (
        <FanOutSkeleton
          heading={<GoogleAdsToolHeading>Run Google Ads Report</GoogleAdsToolHeading>}
          label="Running Google Ads report…"
        />
      )
    }
    const fanOut = parseFanOutData(activity.result, reportData)
    if (!fanOut) {
      return null
    }
    const { data: reports, entries } = fanOut
    return (
      <div aria-label="Google Ads report results" className="w-full min-w-0">
        <FanOutShell
          contextLabel="Account"
          defaultOpen={defaultOpen}
          details={googleAdsReportDetails(activity.args)}
          entries={entries}
          emptyLabel="No Google Ads accounts were queried."
          externalLabel="Customer ID"
          formatContextValue={formatGoogleAdsAccountId}
          heading={<GoogleAdsToolHeading>Run Google Ads Report</GoogleAdsToolHeading>}
        >
          {(entry, index) => {
            const report = reports[index]
            if (!report) {
              return null
            }
            return (
              <div className="grid min-w-0 gap-3">
                {report.rows.length > 0 && report.columns.length > 0 ? (
                  <DataTable
                    columns={report.columns}
                    exportFilename={`google-ads-${entry.externalId}-report.csv`}
                    rows={report.rows}
                    showTotals
                    truncationNote={report.truncationNote}
                  />
                ) : (
                  <p className="text-muted-foreground py-4 text-center text-sm">
                    No report rows returned.
                  </p>
                )}
              </div>
            )
          }}
        </FanOutShell>
      </div>
    )
  },
}

function reportData(value: unknown): GoogleAdsReport | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value["rows"]) ||
    typeof value["row_count"] !== "number" ||
    typeof value["truncated"] !== "boolean" ||
    (value["currency_code"] !== undefined &&
      value["currency_code"] !== null &&
      typeof value["currency_code"] !== "string") ||
    (value["truncation_note"] !== null &&
      value["truncation_note"] !== undefined &&
      typeof value["truncation_note"] !== "string")
  ) {
    return null
  }
  const currencyCode = typeof value["currency_code"] === "string" ? value["currency_code"] : ""
  const rows: DataRow[] = []
  for (const rawRow of value["rows"]) {
    if (!isRecord(rawRow)) {
      return null
    }
    const flattened = flattenRow(rawRow)
    if (!flattened) {
      return null
    }
    rows.push(flattened)
  }
  return {
    columns: reportColumns(rows, currencyCode),
    currencyCode,
    rowCount: value["row_count"],
    rows,
    truncated: value["truncated"],
    truncationNote: typeof value["truncation_note"] === "string" ? value["truncation_note"] : null,
  }
}

function flattenRow(value: Record<string, unknown>): DataRow | null {
  const flattened: DataRow = {}
  const pending: { path: string; value: unknown }[] = Object.entries(value).map(([key, item]) => ({
    path: key,
    value: item,
  }))
  while (pending.length > 0) {
    const next = pending.pop()
    if (!next) {
      break
    }
    if (isScalar(next.value)) {
      flattened[next.path] = next.value
      continue
    }
    if (!isRecord(next.value)) {
      return null
    }
    for (const [key, item] of Object.entries(next.value)) {
      pending.push({ path: `${next.path}.${key}`, value: item })
    }
  }
  return flattened
}

function reportColumns(rows: DataRow[], currencyCode: string): DataColumn[] {
  const keys: string[] = []
  const seen = new Set<string>()
  for (const row of rows) {
    for (const key of Object.keys(row)) {
      if (!seen.has(key)) {
        seen.add(key)
        keys.push(key)
      }
    }
  }
  const labels = reportColumnLabels(keys)
  return keys.map((key, index) => {
    const kind = reportColumnKind(key, rows)
    const usesMicros = isGoogleAdsMicrosColumn(key)
    return {
      key,
      kind,
      label: labels[index] ?? key,
      isMetric: key.startsWith("metrics.") && isNumericKind(kind),
      ...(usesMicros ? { unit: "micros" as const } : {}),
      ...(kind === "currency" && currencyCode ? { currencyCode } : {}),
    }
  })
}

function reportColumnLabels(keys: string[]): string[] {
  const labels = keys.map(shortColumnLabel)
  const duplicateLabels = new Set(labels.filter((label, index) => labels.indexOf(label) !== index))

  return keys.map((key, index) => {
    const label = labels[index] ?? key
    if (!duplicateLabels.has(label)) {
      return label
    }
    const path = key.split(".")
    const context = path.at(-2)
    return context && !NON_ENTITY_COLUMN_PREFIXES.has(context.toLowerCase())
      ? `${humanizeColumnToken(context)} ${label}`
      : label
  })
}

function shortColumnLabel(key: string): string {
  const field = normalizedColumnField(key).replace(/_micros$/i, "")
  return humanizeColumnToken(field)
}

function humanizeColumnToken(value: string): string {
  return value
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .split("_")
    .filter(Boolean)
    .map((part) =>
      REPORT_FIELD_ACRONYMS.has(part.toLowerCase())
        ? part.toUpperCase()
        : titleCaseToken(part, part)
    )
    .join(" ")
}

function normalizedColumnField(key: string): string {
  return (key.split(".").at(-1) ?? key).replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLowerCase()
}

const REPORT_FIELD_ACRONYMS = new Set([
  "cpa",
  "cpc",
  "cpe",
  "cpm",
  "cpv",
  "ctr",
  "id",
  "roas",
  "url",
])
const NON_ENTITY_COLUMN_PREFIXES = new Set(["metrics", "segments"])
const GOOGLE_ADS_IMPLICIT_MICROS_FIELDS = new Set([
  "average_cost",
  "average_cpc",
  "average_cpe",
  "average_cpm",
  "average_cpv",
  "cost_per_all_conversions",
  "cost_per_conversion",
  "cost_per_current_model_attributed_conversion",
  "cost_per_interaction",
])

function reportColumnKind(key: string, rows: DataRow[]): DataColumnKind {
  const field = normalizedColumnField(key)
  if (isGoogleAdsMicrosColumn(key)) {
    return "currency"
  }
  if (
    field === "ctr" ||
    field.endsWith("_rate") ||
    field.endsWith("_share") ||
    field.endsWith("_percentage") ||
    field.endsWith("_percent")
  ) {
    return "percent"
  }
  if (field === "date") {
    return "date"
  }
  if (field.endsWith("_at") || field === "datetime" || field === "date_time") {
    return "datetime"
  }
  if (field === "status") {
    return "status"
  }
  if (field === "id" || field.endsWith("_id")) {
    return "id"
  }
  if (key.startsWith("metrics.") || rows.some((row) => typeof row[key] === "number")) {
    return "number"
  }
  return "text"
}

function isGoogleAdsMicrosColumn(key: string): boolean {
  return isMicrosColumnKey(key) || GOOGLE_ADS_IMPLICIT_MICROS_FIELDS.has(normalizedColumnField(key))
}

function isScalar(value: unknown): value is string | number | boolean | null {
  return (
    value === null ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  )
}

function isNumericKind(kind: DataColumnKind): boolean {
  return kind === "number" || kind === "currency" || kind === "percent"
}
