// apps/web/src/integrations/google_analytics/presenters/realtime.tsx

import { GoogleAnalyticsReportResults } from "@/integrations/google_analytics/components/report-results"
import { parseRealtimeReportData } from "@/integrations/google_analytics/lib/report-model"
import { realtimeDetails } from "@/integrations/google_analytics/lib/tool-details"
import { googleAnalyticsProvider } from "@/integrations/google_analytics/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"

export const googleAnalyticsRealtimePresenter = defineIntegrationReadPresenter(
  googleAnalyticsProvider,
  {
    ariaLabel: "Google Analytics realtime report results",
    details: realtimeDetails,
    emptyLabel: "No Google Analytics properties were queried.",
    heading: "Run Google Analytics Realtime Report",
    parseResult: parseRealtimeReportData,
    progressLabel: "Running Google Analytics realtime report…",
    render: (report, entry) => (
      <GoogleAnalyticsReportResults externalId={entry.externalId} realtime report={report} />
    ),
    tool: "google_analytics_run_realtime_report",
  }
)
