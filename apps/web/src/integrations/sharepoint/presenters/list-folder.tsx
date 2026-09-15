// apps/web/src/integrations/sharepoint/presenters/list-folder.tsx

import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"
import { SharePointItemTable } from "@/integrations/sharepoint/components/item-table"
import { folderResult } from "@/integrations/sharepoint/lib/items"
import { sharePointProvider } from "@/integrations/sharepoint/provider"

export const sharePointListFolderPresenter = defineIntegrationReadPresenter(sharePointProvider, {
  ariaLabel: "SharePoint folder results",
  emptyLabel: "No libraries returned a result.",
  heading: "List SharePoint folder",
  parseResult: folderResult,
  progressLabel: "Listing files and folders…",
  render: ({ rows, hasMore }) => <SharePointItemTable hasMore={hasMore} rows={rows} />,
  tool: "sharepoint_list_folder",
})
