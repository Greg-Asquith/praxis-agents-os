// apps/web/src/integrations/sharepoint/presenters/search-files.tsx

import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"
import { SharePointItemTable } from "@/integrations/sharepoint/components/item-table"
import { searchResult } from "@/integrations/sharepoint/lib/items"
import { sharePointProvider } from "@/integrations/sharepoint/provider"
import { compactDetails, stringDetail } from "@/integrations/tool-details"

export const sharePointSearchFilesPresenter = defineIntegrationReadPresenter(sharePointProvider, {
  ariaLabel: "SharePoint search results",
  details: (args) => compactDetails([stringDetail(args, "query", "Search")]),
  emptyLabel: "No libraries were searched.",
  heading: "Search SharePoint files",
  parseResult: searchResult,
  progressLabel: "Searching libraries…",
  render: (rows) => <SharePointItemTable emptyLabel="0 items found." hasMore={false} rows={rows} />,
  tool: "sharepoint_search_files",
})
