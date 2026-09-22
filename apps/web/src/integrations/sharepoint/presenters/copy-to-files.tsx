// apps/web/src/integrations/sharepoint/presenters/copy-to-files.tsx

import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"
import { SharePointFileHeading } from "@/integrations/sharepoint/components/file-heading"
import { parseCopyResult } from "@/integrations/sharepoint/lib/copy-result"
import { sharePointProvider } from "@/integrations/sharepoint/provider"
import { formatBytes } from "@/lib/format"

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
      <div className="grid min-w-0 gap-1">
        <p className="text-muted-foreground text-xs">Saved in Files</p>
        <p className="text-sm font-medium wrap-break-word">{result.name}</p>
        <p className="text-muted-foreground text-xs wrap-break-word">
          {result.contentType} · {formatBytes(result.sizeBytes)}
        </p>
        <a
          className="text-link hover:text-primary text-xs underline underline-offset-2"
          href={result.fileHref}
        >
          Open in Files
        </a>
      </div>
    </div>
  ),
  tool: "sharepoint_copy_to_files",
})
