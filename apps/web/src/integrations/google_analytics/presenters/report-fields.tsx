// apps/web/src/integrations/google_analytics/presenters/report-fields.tsx

import { GoogleAnalyticsReportFieldsTable } from "@/integrations/google_analytics/components/report-fields-table"
import { parseReportFields } from "@/integrations/google_analytics/lib/report-fields-model"
import { reportFieldsDetails } from "@/integrations/google_analytics/lib/tool-details"
import { googleAnalyticsProvider } from "@/integrations/google_analytics/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"

export const googleAnalyticsReportFieldsPresenter = defineIntegrationReadPresenter(
  googleAnalyticsProvider,
  {
    ariaLabel: "Google Analytics report fields",
    details: reportFieldsDetails,
    emptyLabel: "No Google Analytics properties were queried.",
    heading: "List Google Analytics Report Fields",
    parseResult: parseReportFields,
    progressLabel: "Listing Google Analytics report fields…",
    render: (fields, entry) => (
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
    ),
    tool: "google_analytics_list_report_fields",
  }
)
