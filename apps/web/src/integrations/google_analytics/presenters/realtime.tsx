// apps/web/src/integrations/google_analytics/presenters/realtime.tsx

import { parseFanOutData } from "@/components/tool-ui/fan-out"
import { FanOutShell, FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { GoogleAnalyticsReportResults } from "@/integrations/google_analytics/components/report-results"
import { GoogleAnalyticsToolHeading } from "@/integrations/google_analytics/components/tool-heading"
import { parseReportData } from "@/integrations/google_analytics/lib/report-model"
import { realtimeDetails } from "@/integrations/google_analytics/lib/tool-details"
import type { ToolRowPresenter } from "@/integrations/contract"
import { isRecord } from "@/lib/guards"

export const realtimePresenter: ToolRowPresenter = {
  key: "google-analytics-run-realtime-report",
  matches: (activity) => activity.name === "google_analytics_run_realtime_report",
  render: ({ activity, defaultOpen }) => {
    if (activity.status === "running") {
      return (
        <FanOutSkeleton
          heading={
            <GoogleAnalyticsToolHeading>
              Run Google Analytics Realtime Report
            </GoogleAnalyticsToolHeading>
          }
          label="Running Google Analytics realtime report…"
        />
      )
    }
    const fanOut = parseFanOutData(activity.result, parseRealtimeReportData)
    if (!fanOut) return null
    return (
      <div aria-label="Google Analytics realtime report results" className="w-full min-w-0">
        <FanOutShell
          contextLabel="Property"
          defaultOpen={defaultOpen}
          details={realtimeDetails(activity.args)}
          emptyLabel="No Google Analytics properties were queried."
          externalLabel="Property ID"
          entries={fanOut.entries}
          heading={
            <GoogleAnalyticsToolHeading>
              Run Google Analytics Realtime Report
            </GoogleAnalyticsToolHeading>
          }
        >
          {(entry, index) => {
            const report = fanOut.data[index]
            return report ? (
              <GoogleAnalyticsReportResults
                externalId={entry.externalId}
                realtime
                report={report}
              />
            ) : null
          }}
        </FanOutShell>
      </div>
    )
  },
}

function parseRealtimeReportData(value: unknown) {
  if (!isRecord(value) || !Array.isArray(value["window"])) {
    return null
  }
  for (const range of value["window"]) {
    if (
      !isRecord(range) ||
      typeof range["start_minutes_ago"] !== "number" ||
      typeof range["end_minutes_ago"] !== "number"
    )
      return null
  }
  return parseReportData({
    ...value,
    metadata: {
      currency_code: "",
      data_loss_from_other_row: false,
      sampled: false,
      sampling_notes: [],
      thresholded: false,
    },
  })
}
