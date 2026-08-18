// apps/web/src/integrations/google_analytics/presenters/report-fields.tsx

import type { DataRow } from "@/components/ui/data-table"
import { parseFanOutData } from "@/components/tool-ui/fan-out"
import { FanOutShell, FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { GoogleAnalyticsToolHeading } from "@/integrations/google_analytics/components/tool-heading"
import { GoogleAnalyticsReportFieldsTable } from "@/integrations/google_analytics/components/report-fields-table"
import { reportFieldsDetails } from "@/integrations/google_analytics/lib/tool-details"
import type { ToolRowPresenter } from "@/integrations/contract"
import { isRecord } from "@/lib/guards"

type ReportFields = {
  dimensionCount: number
  dimensions: DataRow[]
  metricCount: number
  metrics: DataRow[]
  truncated: boolean
}

export const reportFieldsPresenter: ToolRowPresenter = {
  key: "google-analytics-list-report-fields",
  matches: (activity) => activity.name === "google_analytics_list_report_fields",
  render: ({ activity, defaultOpen }) => {
    if (activity.status === "running") {
      return (
        <FanOutSkeleton
          heading={
            <GoogleAnalyticsToolHeading>
              List Google Analytics Report Fields
            </GoogleAnalyticsToolHeading>
          }
          label="Listing Google Analytics report fields…"
        />
      )
    }
    const fanOut = parseFanOutData(activity.result, parseReportFields)
    if (!fanOut) return null
    return (
      <div aria-label="Google Analytics report fields" className="w-full min-w-0">
        <FanOutShell
          contextLabel="Property"
          defaultOpen={defaultOpen}
          details={reportFieldsDetails(activity.args)}
          emptyLabel="No Google Analytics properties were queried."
          externalLabel="Property ID"
          entries={fanOut.entries}
          heading={
            <GoogleAnalyticsToolHeading>
              List Google Analytics Report Fields
            </GoogleAnalyticsToolHeading>
          }
        >
          {(entry, index) => {
            const fields = fanOut.data[index]
            if (!fields) return null
            return (
              <div className="grid min-w-0 gap-5">
                <GoogleAnalyticsReportFieldsTable
                  count={fields.dimensionCount}
                  externalId={entry.externalId}
                  fields={fields.dimensions}
                  kind="dimensions"
                  label="Dimensions"
                  truncated={fields.truncated}
                />
                <GoogleAnalyticsReportFieldsTable
                  count={fields.metricCount}
                  externalId={entry.externalId}
                  fields={fields.metrics}
                  kind="metrics"
                  label="Metrics"
                  truncated={fields.truncated}
                />
              </div>
            )
          }}
        </FanOutShell>
      </div>
    )
  },
}

function parseReportFields(value: unknown): ReportFields | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value["dimensions"]) ||
    !Array.isArray(value["metrics"]) ||
    !isCount(value["dimension_count"]) ||
    !isCount(value["metric_count"]) ||
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

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0
}
