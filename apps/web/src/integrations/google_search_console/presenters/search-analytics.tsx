// apps/web/src/integrations/google_search_console/presenters/search-analytics.tsx

import { parseFanOutData } from "@/components/tool-ui/fan-out"
import { FanOutShell, FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { SearchAnalyticsResults } from "@/integrations/google_search_console/components/search-analytics-results"
import { GoogleSearchConsoleToolHeading } from "@/integrations/google_search_console/components/tool-heading"
import { parseSearchAnalyticsData } from "@/integrations/google_search_console/lib/search-analytics-model"
import { searchAnalyticsDetails } from "@/integrations/google_search_console/lib/tool-details"
import type { ToolRowPresenter } from "@/integrations/contract"

export const searchAnalyticsPresenter: ToolRowPresenter = {
  key: "google-search-console-query-search-analytics",
  matches: (activity) => activity.name === "google_search_console_query_search_analytics",
  render: ({ activity, defaultOpen }) => {
    if (activity.status === "running") {
      return (
        <FanOutSkeleton
          heading={
            <GoogleSearchConsoleToolHeading>Query Search Analytics</GoogleSearchConsoleToolHeading>
          }
          label="Querying Search Analytics…"
        />
      )
    }
    const fanOut = parseFanOutData(activity.result, parseSearchAnalyticsData)
    if (!fanOut) return null
    return (
      <div aria-label="Search Analytics results" className="w-full min-w-0">
        <FanOutShell
          contextLabel="Site"
          defaultOpen={defaultOpen}
          details={searchAnalyticsDetails(activity.args)}
          emptyLabel="No Search Console sites were queried."
          entries={fanOut.entries}
          externalLabel="Site URL"
          heading={
            <GoogleSearchConsoleToolHeading>Query Search Analytics</GoogleSearchConsoleToolHeading>
          }
        >
          {(entry, index) => {
            const report = fanOut.data[index]
            return report ? (
              <SearchAnalyticsResults externalId={entry.externalId} report={report} />
            ) : null
          }}
        </FanOutShell>
      </div>
    )
  },
}
