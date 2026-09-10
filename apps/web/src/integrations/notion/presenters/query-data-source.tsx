// apps/web/src/integrations/notion/presenters/query-data-source.tsx

import { NotionQueryResult } from "@/integrations/notion/components/read-results"
import { parseQueryData } from "@/integrations/notion/lib/read-results"
import { notionProvider } from "@/integrations/notion/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"

export const notionQueryDataSourcePresenter = defineIntegrationReadPresenter(notionProvider, {
  ariaLabel: "Query Notion Data Source results",
  emptyLabel: "No Notion workspaces were queried.",
  heading: "Query Notion Data Source",
  parseResult: parseQueryData,
  progressLabel: "Querying Notion data source…",
  render: (data) => <NotionQueryResult data={data} />,
  tool: "notion_query_data_source",
})
