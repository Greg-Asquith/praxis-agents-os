// apps/web/src/integrations/sharepoint/presenters/open-link.tsx

import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"
import { SharePointItemTable } from "@/integrations/sharepoint/components/item-table"
import { SharePointLinkFailure } from "@/integrations/sharepoint/components/link-failure"
import { itemRows } from "@/integrations/sharepoint/lib/items"
import { sharePointProvider } from "@/integrations/sharepoint/provider"
import { compactDetails, stringDetail } from "@/integrations/tool-details"

export const sharePointOpenLinkPresenter = defineIntegrationReadPresenter(sharePointProvider, {
  ariaLabel: "SharePoint link results",
  details: (args) => compactDetails([stringDetail(args, "url", "Link")]),
  emptyLabel: "No library returned this link.",
  heading: "Open SharePoint link",
  parseResult: (value) => itemRows([value]),
  progressLabel: "Opening SharePoint link…",
  render: (rows) => <SharePointItemTable hasMore={false} rows={rows} />,
  renderFailed: (entry) => <SharePointLinkFailure entry={entry} />,
  tool: "sharepoint_open_link",
})
