// apps/web/src/integrations/notion/presenters/read-page.tsx

import { parseFanOutData } from "@/components/tool-ui/fan-out"
import type { ToolRowPresenter } from "@/integrations/contract"
import {
  NotionFanOut,
  NotionPageResult,
  NotionSkeleton,
} from "@/integrations/notion/components/read-results"
import { parsePageData } from "@/integrations/notion/lib/read-results"

export const notionReadPagePresenter: ToolRowPresenter = {
  key: "notion-read-page",
  matches: (activity) => activity.name === "notion_read_page",
  render: ({ activity, defaultOpen }) => {
    if (activity.status === "running") {
      return <NotionSkeleton label="Reading Notion page…" title="Read Notion Page" />
    }
    const fanOut = parseFanOutData(activity.result, parsePageData)
    if (!fanOut) {
      return null
    }
    return (
      <NotionFanOut defaultOpen={defaultOpen} entries={fanOut.entries} title="Read Notion Page">
        {(_entry, index) => {
          const data = fanOut.data[index]
          return data ? <NotionPageResult data={data} /> : null
        }}
      </NotionFanOut>
    )
  },
}
