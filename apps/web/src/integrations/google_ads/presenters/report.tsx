// apps/web/src/integrations/google_ads/presenters/report.tsx

import { EmptyResult } from "@/components/tool-ui/empty-result"
import { DataTable } from "@/components/ui/data-table"
import { parseGoogleAdsReport } from "@/integrations/google_ads/lib/report-model"
import { googleAdsReportDetails } from "@/integrations/google_ads/lib/tool-details"
import { googleAdsProvider } from "@/integrations/google_ads/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"

export const googleAdsReportPresenter = defineIntegrationReadPresenter(googleAdsProvider, {
  ariaLabel: "Google Ads report results",
  details: googleAdsReportDetails,
  emptyLabel: "No Google Ads accounts were queried.",
  heading: "Run Google Ads Report",
  parseResult: parseGoogleAdsReport,
  progressLabel: "Running Google Ads report…",
  render: (report, entry) =>
    report.rows.length > 0 && report.columns.length > 0 ? (
      <DataTable
        columns={report.columns}
        exportFilename={`google-ads-${entry.externalId}-report.csv`}
        rows={report.rows}
        showTotals
        truncationNote={report.truncationNote}
      />
    ) : (
      <EmptyResult>No report rows returned.</EmptyResult>
    ),
  tool: "google_ads_run_report",
})
