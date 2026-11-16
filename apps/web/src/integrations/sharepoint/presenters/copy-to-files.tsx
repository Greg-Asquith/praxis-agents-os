// apps/web/src/integrations/sharepoint/presenters/copy-to-files.tsx

import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"
import { SavedFileSummary } from "@/integrations/saved-file-summary"
import { SharePointFileHeading } from "@/integrations/sharepoint/components/file-heading"
import { parseCopyResult } from "@/integrations/sharepoint/lib/copy-result"
import { sharePointProvider } from "@/integrations/sharepoint/provider"

export const sharePointCopyToFilesPresenter = defineIntegrationReadPresenter(sharePointProvider, {
  ariaLabel: "Copy SharePoint file to Files results",
  emptyLabel: "No library returned a file to copy.",
  heading: "Copy SharePoint file to Files",
  parseResult: parseCopyResult,
  progressLabel: "Copying SharePoint file to Files…",
  render: (result) => (
    <div className="grid min-w-0 gap-3">
      <div>
        <p className="text-muted-foreground mb-1 text-xs">Source file</p>
        <SharePointFileHeading name={result.source.name} webUrl={result.source.webUrl} />
      </div>
      <SavedFileSummary file={result} />
    </div>
  ),
  tool: "sharepoint_copy_to_files",
})
