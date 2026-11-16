// apps/web/src/integrations/sharepoint/components/find-results.tsx

import { Badge } from "@/components/ui/badge"
import { SharePointFileHeading } from "@/integrations/sharepoint/components/file-heading"
import type { SharePointFindResults } from "@/integrations/sharepoint/lib/find-results"
import { TextMatchList } from "@/integrations/text-match-list"

export function SharePointFindView({
  result,
  query,
}: {
  result: SharePointFindResults
  query: string | null
}) {
  return (
    <div className="grid min-w-0 gap-3">
      <div className="flex min-w-0 flex-wrap items-start gap-2">
        <SharePointFileHeading name={result.name} webUrl={result.webUrl} />
        {result.limitReached ? <Badge variant="warning">Conversion limit reached</Badge> : null}
      </div>
      <TextMatchList found={result} query={query} />
    </div>
  )
}
