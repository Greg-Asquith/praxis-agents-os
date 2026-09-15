// apps/web/src/integrations/sharepoint/presenters/read-file.tsx

import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"
import { SharePointFileView } from "@/integrations/sharepoint/components/file-content"
import { parseFileContent } from "@/integrations/sharepoint/lib/file-content"
import { sharePointProvider } from "@/integrations/sharepoint/provider"

export const sharePointReadFilePresenter = defineIntegrationReadPresenter(sharePointProvider, {
  ariaLabel: "Read SharePoint file results",
  emptyLabel: "No library returned this file.",
  heading: "Read SharePoint file",
  parseResult: parseFileContent,
  progressLabel: "Reading file…",
  render: (file) => <SharePointFileView file={file} />,
  tool: "sharepoint_read_file",
})
