// apps/web/src/integrations/google_search_console/presenters/search-analytics.tsx

import { SearchAnalyticsResults } from "@/integrations/google_search_console/components/search-analytics-results"
import { parseSearchAnalyticsData } from "@/integrations/google_search_console/lib/search-analytics-model"
import { searchAnalyticsDetails } from "@/integrations/google_search_console/lib/tool-details"
import { googleSearchConsoleProvider } from "@/integrations/google_search_console/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"

export const googleSearchConsoleSearchAnalyticsPresenter = defineIntegrationReadPresenter(
  googleSearchConsoleProvider,
  {
    ariaLabel: "Search Analytics results",
    details: searchAnalyticsDetails,
    emptyLabel: "No Search Console sites were queried.",
    heading: "Query Search Analytics",
    parseResult: parseSearchAnalyticsData,
    progressLabel: "Querying Search Analytics…",
    render: (report, entry) => (
      <SearchAnalyticsResults externalId={entry.externalId} report={report} />
    ),
    tool: "google_search_console_query_search_analytics",
  }
)
