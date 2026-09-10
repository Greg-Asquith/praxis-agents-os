// apps/web/src/integrations/notion/presenters/read-page.tsx

import { NotionPageResult } from "@/integrations/notion/components/read-results"
import { parsePageData } from "@/integrations/notion/lib/read-results"
import { notionProvider } from "@/integrations/notion/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"

export const notionReadPagePresenter = defineIntegrationReadPresenter(notionProvider, {
  ariaLabel: "Read Notion Page results",
  emptyLabel: "No Notion workspaces were queried.",
  heading: "Read Notion Page",
  parseResult: parsePageData,
  progressLabel: "Reading Notion page…",
  render: (data) => <NotionPageResult data={data} />,
  tool: "notion_read_page",
})
