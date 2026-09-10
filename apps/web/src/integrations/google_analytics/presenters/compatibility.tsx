// apps/web/src/integrations/google_analytics/presenters/compatibility.tsx

import { GoogleAnalyticsCompatibilityResults } from "@/integrations/google_analytics/components/compatibility-results"
import { parseCompatibility } from "@/integrations/google_analytics/lib/compatibility-model"
import { compatibilityDetails } from "@/integrations/google_analytics/lib/tool-details"
import { googleAnalyticsProvider } from "@/integrations/google_analytics/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"

export const googleAnalyticsCompatibilityPresenter = defineIntegrationReadPresenter(
  googleAnalyticsProvider,
  {
    ariaLabel: "Google Analytics field compatibility",
    details: compatibilityDetails,
    emptyLabel: "No Google Analytics properties were queried.",
    heading: "Check Google Analytics Report Fields",
    parseResult: parseCompatibility,
    progressLabel: "Checking Google Analytics report fields…",
    render: (result) => <GoogleAnalyticsCompatibilityResults result={result} />,
    tool: "google_analytics_check_report_fields",
  }
)
