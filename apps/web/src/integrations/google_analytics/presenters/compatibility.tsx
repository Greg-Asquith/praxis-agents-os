// apps/web/src/integrations/google_analytics/presenters/compatibility.tsx

import { AlertTriangleIcon, CheckCircle2Icon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { parseFanOutData } from "@/components/tool-ui/fan-out"
import { FanOutShell, FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { GoogleAnalyticsToolHeading } from "@/integrations/google_analytics/components/tool-heading"
import { metricLabel } from "@/integrations/google_analytics/lib/report-model"
import { compatibilityDetails } from "@/integrations/google_analytics/lib/tool-details"
import type { ToolRowPresenter } from "@/integrations/contract"
import { isRecord } from "@/lib/guards"

type FieldCompatibility = {
  apiName: string
  compatible: boolean
}

type Compatibility = {
  compatible: boolean
  fields: FieldCompatibility[]
  incompatibleFields: string[]
}

export const compatibilityPresenter: ToolRowPresenter = {
  key: "google-analytics-check-report-fields",
  matches: (activity) => activity.name === "google_analytics_check_report_fields",
  render: ({ activity, defaultOpen }) => {
    if (activity.status === "running") {
      return (
        <FanOutSkeleton
          heading={
            <GoogleAnalyticsToolHeading>
              Check Google Analytics Report Fields
            </GoogleAnalyticsToolHeading>
          }
          label="Checking Google Analytics report fields…"
        />
      )
    }
    const fanOut = parseFanOutData(activity.result, parseCompatibility)
    if (!fanOut) return null
    return (
      <div aria-label="Google Analytics field compatibility" className="w-full min-w-0">
        <FanOutShell
          contextLabel="Property"
          defaultOpen={defaultOpen}
          details={compatibilityDetails(activity.args)}
          emptyLabel="No Google Analytics properties were queried."
          externalLabel="Property ID"
          entries={fanOut.entries}
          heading={
            <GoogleAnalyticsToolHeading>
              Check Google Analytics Report Fields
            </GoogleAnalyticsToolHeading>
          }
        >
          {(_entry, index) => {
            const result = fanOut.data[index]
            if (!result) return null
            return (
              <div className="grid gap-3">
                <p className="flex items-center gap-2 text-sm font-medium">
                  {result.compatible ? (
                    <CheckCircle2Icon aria-hidden="true" className="text-success size-4" />
                  ) : (
                    <AlertTriangleIcon
                      aria-hidden="true"
                      className="text-warning-foreground size-4"
                    />
                  )}
                  {result.compatible
                    ? "These can be reported together."
                    : `${String(result.incompatibleFields.length)} ${result.incompatibleFields.length === 1 ? "field can't" : "fields can't"} be combined.`}
                </p>
                <ul className="divide-border divide-y">
                  {result.fields.map((field) => (
                    <li
                      className="flex items-center justify-between gap-3 py-2 text-sm"
                      key={field.apiName}
                    >
                      <span>
                        {metricLabel(field.apiName)}{" "}
                        <span className="text-muted-foreground font-mono text-xs">
                          {field.apiName}
                        </span>
                      </span>
                      <Badge variant={field.compatible ? "success" : "warning"}>
                        {field.compatible ? "Compatible" : "Incompatible"}
                      </Badge>
                    </li>
                  ))}
                </ul>
              </div>
            )
          }}
        </FanOutShell>
      </div>
    )
  },
}

function parseCompatibility(value: unknown): Compatibility | null {
  if (
    !isRecord(value) ||
    typeof value["compatible"] !== "boolean" ||
    !Array.isArray(value["dimensions"]) ||
    !Array.isArray(value["metrics"]) ||
    !Array.isArray(value["incompatible_fields"])
  )
    return null
  const dimensions = parseFields(value["dimensions"])
  const metrics = parseFields(value["metrics"])
  const incompatibleFields = value["incompatible_fields"]
  if (
    !dimensions ||
    !metrics ||
    !incompatibleFields.every((item): item is string => typeof item === "string")
  )
    return null
  const fields = [...dimensions, ...metrics]
  if (value["compatible"] !== (incompatibleFields.length === 0)) return null
  return { compatible: value["compatible"], fields, incompatibleFields }
}

function parseFields(values: unknown[]): FieldCompatibility[] | null {
  const fields: FieldCompatibility[] = []
  for (const value of values) {
    if (
      !isRecord(value) ||
      typeof value["api_name"] !== "string" ||
      (value["compatibility"] !== "COMPATIBLE" && value["compatibility"] !== "INCOMPATIBLE")
    )
      return null
    fields.push({ apiName: value["api_name"], compatible: value["compatibility"] === "COMPATIBLE" })
  }
  return fields
}
