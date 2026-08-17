// apps/web/src/integrations/google_analytics/presenters/report.tsx

import { parseFanOutData } from "@/components/tool-ui/fan-out"
import { FanOutShell, FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { GoogleAnalyticsReportResults } from "@/integrations/google_analytics/components/report-results"
import { GoogleAnalyticsToolHeading } from "@/integrations/google_analytics/components/tool-heading"
import { parseReportData } from "@/integrations/google_analytics/lib/report-model"
import { reportDetails } from "@/integrations/google_analytics/lib/tool-details"
import type { ToolRowPresenter } from "@/integrations/contract"

export const reportPresenter: ToolRowPresenter = {
  key: "google-analytics-run-report",
  matches: (activity) => activity.name === "google_analytics_run_report",
  render: ({ activity, defaultOpen }) => {
    if (activity.status === "running") {
      return (
        <FanOutSkeleton
          heading={
            <GoogleAnalyticsToolHeading>Run Google Analytics Report</GoogleAnalyticsToolHeading>
          }
          label="Running Google Analytics report…"
        />
      )
    }
    const fanOut = parseFanOutData(activity.result, parseReportData)
    if (!fanOut) return null
    return (
      <div aria-label="Google Analytics report results" className="w-full min-w-0">
        <FanOutShell
          contextLabel="Property"
          defaultOpen={defaultOpen}
          details={reportDetails(activity.args)}
          emptyLabel="No Google Analytics properties were queried."
          externalLabel="Property ID"
          entries={fanOut.entries}
          heading={
            <GoogleAnalyticsToolHeading>Run Google Analytics Report</GoogleAnalyticsToolHeading>
          }
        >
          {(entry, index) => {
            const report = fanOut.data[index]
            return report ? (
              <GoogleAnalyticsReportResults externalId={entry.externalId} report={report} />
            ) : null
          }}
        </FanOutShell>
      </div>
    )
  },
}
