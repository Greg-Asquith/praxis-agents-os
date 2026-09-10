// apps/web/src/integrations/notion/presenters/search-pages.tsx

import { NotionSearchResult } from "@/integrations/notion/components/read-results"
import { parseSearchData } from "@/integrations/notion/lib/read-results"
import { notionProvider } from "@/integrations/notion/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"

export const notionSearchPagesPresenter = defineIntegrationReadPresenter(notionProvider, {
  ariaLabel: "Search Notion results",
  emptyLabel: "No Notion workspaces were queried.",
  heading: "Search Notion",
  parseResult: parseSearchData,
  progressLabel: "Searching Notion…",
  render: (data) => <NotionSearchResult data={data} />,
  tool: "notion_search_pages",
})
