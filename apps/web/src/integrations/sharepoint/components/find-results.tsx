// apps/web/src/integrations/sharepoint/components/find-results.tsx

import { Badge } from "@/components/ui/badge"
import { SharePointFileHeading } from "@/integrations/sharepoint/components/file-heading"
import {
  splitExcerptMatch,
  type SharePointFindResults,
} from "@/integrations/sharepoint/lib/find-results"

function MatchExcerpt({ excerpt, query }: { excerpt: string; query: string | null }) {
  const parts = splitExcerptMatch(excerpt, query)
  if (!parts) return excerpt
  return (
    <>
      {parts.before}
      <strong>{parts.match}</strong>
      {parts.after}
    </>
  )
}

export function SharePointFindView({
  result,
  query,
}: {
  result: SharePointFindResults
  query: string | null
}) {
  const count = result.matches.length
  const countLabel = count === 1 ? "1 match" : `${String(count)} matches`
  return (
    <div className="grid min-w-0 gap-3">
      <div className="flex min-w-0 flex-wrap items-start gap-2">
        <SharePointFileHeading name={result.name} webUrl={result.webUrl} />
        {result.limitReached ? <Badge variant="warning">Conversion limit reached</Badge> : null}
      </div>
      <p className="text-muted-foreground text-xs">
        {result.hasMore
          ? `Showing the first ${countLabel}`
          : count === 0
            ? "No matches"
            : countLabel}
      </p>
      {count > 0 ? (
        <ul className="grid max-h-96 min-w-0 gap-2 overflow-auto">
          {result.matches.map((match, index) => (
            <li
              className="border-border bg-muted/20 rounded-lg border p-3 text-sm wrap-anywhere whitespace-pre-wrap"
              key={`${String(match.offset)}:${String(index)}`}
            >
              <MatchExcerpt excerpt={match.excerpt} query={query} />
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
