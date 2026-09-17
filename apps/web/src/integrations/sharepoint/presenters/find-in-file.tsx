// apps/web/src/integrations/sharepoint/presenters/find-in-file.tsx

import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"
import { SharePointFindView } from "@/integrations/sharepoint/components/find-results"
import { findQuery, parseFindResults } from "@/integrations/sharepoint/lib/find-results"
import { sharePointProvider } from "@/integrations/sharepoint/provider"

export const sharePointFindInFilePresenter = defineIntegrationReadPresenter(sharePointProvider, {
  ariaLabel: "SharePoint find in file results",
  details: (args) => {
    const query = findQuery(args)
    return query === null ? [] : [{ label: "Search", value: query }]
  },
  emptyLabel: "No library returned a search result.",
  heading: "Find text in SharePoint file",
  parseResult: parseFindResults,
  progressLabel: "Searching file…",
  render: (result, _entry, args) => <SharePointFindView query={findQuery(args)} result={result} />,
  tool: "sharepoint_find_in_file",
})
