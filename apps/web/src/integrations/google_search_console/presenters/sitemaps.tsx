// apps/web/src/integrations/google_search_console/presenters/sitemaps.tsx

import { parseFanOutData } from "@/components/tool-ui/fan-out"
import { FanOutShell, FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { SitemapsTable } from "@/integrations/google_search_console/components/sitemaps-table"
import { GoogleSearchConsoleToolHeading } from "@/integrations/google_search_console/components/tool-heading"
import { parseSitemapsData } from "@/integrations/google_search_console/lib/sitemaps-model"
import type { ToolRowPresenter } from "@/integrations/contract"

export const sitemapsPresenter: ToolRowPresenter = {
  key: "google-search-console-list-sitemaps",
  matches: (activity) => activity.name === "google_search_console_list_sitemaps",
  render: ({ activity, defaultOpen }) => {
    if (activity.status === "running") {
      return (
        <FanOutSkeleton
          heading={
            <GoogleSearchConsoleToolHeading>
              List Search Console Sitemaps
            </GoogleSearchConsoleToolHeading>
          }
          label="Listing Search Console sitemaps…"
        />
      )
    }
    const fanOut = parseFanOutData(activity.result, parseSitemapsData)
    if (!fanOut) return null
    return (
      <div aria-label="Search Console sitemap results" className="w-full min-w-0">
        <FanOutShell
          contextLabel="Site"
          defaultOpen={defaultOpen}
          emptyLabel="No Search Console sites were queried."
          entries={fanOut.entries}
          externalLabel="Site URL"
          heading={
            <GoogleSearchConsoleToolHeading>
              List Search Console Sitemaps
            </GoogleSearchConsoleToolHeading>
          }
        >
          {(entry, index) => {
            const sitemaps = fanOut.data[index]
            return sitemaps ? <SitemapsTable externalId={entry.externalId} rows={sitemaps} /> : null
          }}
        </FanOutShell>
      </div>
    )
  },
}
