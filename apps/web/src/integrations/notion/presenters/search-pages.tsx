// apps/web/src/integrations/notion/presenters/search-pages.tsx

import { parseFanOutData } from "@/components/tool-ui/fan-out"
import type { ToolRowPresenter } from "@/integrations/contract"
import {
  NotionFanOut,
  NotionSearchResult,
  NotionSkeleton,
} from "@/integrations/notion/components/read-results"
import { parseSearchData } from "@/integrations/notion/lib/read-results"

export const notionSearchPagesPresenter: ToolRowPresenter = {
  key: "notion-search-pages",
  matches: (activity) => activity.name === "notion_search_pages",
  render: ({ activity, defaultOpen }) => {
    if (activity.status === "running") {
      return <NotionSkeleton label="Searching Notion…" title="Search Notion" />
    }
    const fanOut = parseFanOutData(activity.result, parseSearchData)
    if (!fanOut) {
      return null
    }
    return (
      <NotionFanOut defaultOpen={defaultOpen} entries={fanOut.entries} title="Search Notion">
        {(_entry, index) => {
          const data = fanOut.data[index]
          return data ? <NotionSearchResult data={data} /> : null
        }}
      </NotionFanOut>
    )
  },
}
