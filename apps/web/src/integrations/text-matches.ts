// apps/web/src/integrations/text-matches.ts

import { nodeText } from "@/components/tool-ui/untrusted-node"
import { isNonNegativeInteger, isRecord } from "@/lib/guards"

type TextMatch = { offset: number; excerpt: string }

export type TextMatches = {
  hasMore: boolean
  matches: TextMatch[]
  totalBytes: number
}

export function parseTextMatches(value: Record<string, unknown>): TextMatches | null {
  const matches = value["matches"]
  const totalBytes = value["total_bytes"]
  if (
    !Array.isArray(matches) ||
    matches.length > 25 ||
    value["count"] !== matches.length ||
    !isNonNegativeInteger(totalBytes) ||
    typeof value["has_more"] !== "boolean"
  )
    return null
  const parsed: TextMatch[] = []
  for (const match of matches) {
    if (!isRecord(match) || !isNonNegativeInteger(match["offset"])) return null
    const excerpt = nodeText(match["excerpt"])
    if (excerpt === null || match["offset"] >= totalBytes) return null
    parsed.push({ offset: match["offset"], excerpt })
  }
  return { hasMore: value["has_more"], matches: parsed, totalBytes }
}

export function findQuery(args: unknown): string | null {
  if (!isRecord(args) || typeof args["query"] !== "string") return null
  const query = args["query"]
  return query.length > 0 && Array.from(query).length <= 200 ? query : null
}

export function splitExcerptMatch(excerpt: string, query: string | null) {
  if (!query) return null
  const foldedQuery = query.toLowerCase()
  const matchStart = excerpt.toLowerCase().indexOf(foldedQuery)
  if (matchStart < 0) return null
  let foldedOffset = 0
  let offset = 0
  let start = 0
  for (const character of excerpt) {
    // Lowercasing can expand a character; slice the original text at its own boundaries.
    if (foldedOffset <= matchStart) start = offset
    foldedOffset += character.toLowerCase().length
    offset += character.length
    if (foldedOffset >= matchStart + foldedQuery.length) {
      return {
        before: excerpt.slice(0, start),
        match: excerpt.slice(start, offset),
        after: excerpt.slice(offset),
      }
    }
  }
  return null
}
