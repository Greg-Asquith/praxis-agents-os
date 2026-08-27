// apps/web/src/integrations/notion/presenters/query-data-source.tsx

import { parseFanOutData } from "@/components/tool-ui/fan-out"
import type { ToolRowPresenter } from "@/integrations/contract"
import {
  NotionFanOut,
  NotionQueryResult,
  NotionSkeleton,
} from "@/integrations/notion/components/read-results"
import { parseQueryData } from "@/integrations/notion/lib/read-results"

export const notionQueryDataSourcePresenter: ToolRowPresenter = {
  key: "notion-query-data-source",
  matches: (activity) => activity.name === "notion_query_data_source",
  render: ({ activity, defaultOpen }) => {
    if (activity.status === "running") {
      return (
        <NotionSkeleton label="Querying Notion data source…" title="Query Notion Data Source" />
      )
    }
    const fanOut = parseFanOutData(activity.result, parseQueryData)
    if (!fanOut) {
      return null
    }
    return (
      <NotionFanOut
        defaultOpen={defaultOpen}
        entries={fanOut.entries}
        title="Query Notion Data Source"
      >
        {(_entry, index) => {
          const data = fanOut.data[index]
          return data ? <NotionQueryResult data={data} /> : null
        }}
      </NotionFanOut>
    )
  },
}
