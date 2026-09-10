// apps/web/src/integrations/google_analytics/presenters/report.tsx

import { GoogleAnalyticsReportResults } from "@/integrations/google_analytics/components/report-results"
import { parseReportData } from "@/integrations/google_analytics/lib/report-model"
import { reportDetails } from "@/integrations/google_analytics/lib/tool-details"
import { googleAnalyticsProvider } from "@/integrations/google_analytics/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"

export const googleAnalyticsReportPresenter = defineIntegrationReadPresenter(
  googleAnalyticsProvider,
  {
    ariaLabel: "Google Analytics report results",
    details: reportDetails,
    emptyLabel: "No Google Analytics properties were queried.",
    heading: "Run Google Analytics Report",
    parseResult: parseReportData,
    progressLabel: "Running Google Analytics report…",
    render: (report, entry) => (
      <GoogleAnalyticsReportResults externalId={entry.externalId} report={report} />
    ),
    tool: "google_analytics_run_report",
  }
)
