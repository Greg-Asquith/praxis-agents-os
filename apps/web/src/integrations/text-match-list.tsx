// apps/web/src/integrations/text-match-list.tsx

import { splitExcerptMatch, type TextMatches } from "@/integrations/text-matches"

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

export function TextMatchList({ found, query }: { found: TextMatches; query: string | null }) {
  const count = found.matches.length
  const countLabel = count === 1 ? "1 match" : `${String(count)} matches`
  return (
    <>
      <p className="text-muted-foreground text-xs">
        {found.hasMore
          ? `Showing the first ${countLabel}`
          : count === 0
            ? "No matches"
            : countLabel}
      </p>
      {count > 0 ? (
        <ul className="grid max-h-96 min-w-0 gap-2 overflow-auto">
          {found.matches.map((match, index) => (
            <li
              className="border-border bg-muted/20 rounded-lg border p-3 text-sm wrap-anywhere whitespace-pre-wrap"
              key={`${String(match.offset)}:${String(index)}`}
            >
              <MatchExcerpt excerpt={match.excerpt} query={query} />
            </li>
          ))}
        </ul>
      ) : null}
    </>
  )
}
