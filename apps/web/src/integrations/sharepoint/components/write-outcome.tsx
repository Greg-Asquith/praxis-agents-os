// apps/web/src/integrations/sharepoint/components/write-outcome.tsx

import { SharePointFileHeading } from "@/integrations/sharepoint/components/file-heading"
import { sharePointWriteLocation } from "@/integrations/sharepoint/lib/write-location"
import type { SharePointWriteResult } from "@/integrations/sharepoint/lib/write-results"
import { formatBytes } from "@/lib/format"

export function SharePointWriteOutcome({
  result,
  description,
}: {
  result: SharePointWriteResult | null
  description: string | null
}) {
  const item = result?.item
  return (
    <div className="grid min-w-0 gap-3">
      {description ? (
        <p className="text-sm wrap-break-word whitespace-pre-wrap">{description}</p>
      ) : null}
      {item ? (
        <SharePointFileHeading name={item.name} webUrl={item.webUrl}>
          <p className="text-muted-foreground mt-0.5 text-xs wrap-break-word whitespace-pre-wrap">
            {sharePointWriteLocation(item.path)} · {formatBytes(item.sizeBytes)}
          </p>
        </SharePointFileHeading>
      ) : null}
    </div>
  )
}
