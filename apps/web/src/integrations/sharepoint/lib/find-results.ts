// apps/web/src/integrations/sharepoint/lib/find-results.ts

import { safeHttpUrl } from "@/components/tool-ui/field-resolution"
import { nodeText } from "@/components/tool-ui/untrusted-node"
import { isNonNegativeInteger, isRecord } from "@/lib/guards"

export type SharePointFindResults = {
  hasMore: boolean
  limitReached: boolean
  matches: { offset: number; excerpt: string }[]
  name: string
  webUrl: string | null
}

export function parseFindResults(value: unknown): SharePointFindResults | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value["matches"]) ||
    value["matches"].length > 25 ||
    value["count"] !== value["matches"].length ||
    !isNonNegativeInteger(value["total_bytes"]) ||
    typeof value["limit_reached"] !== "boolean" ||
    typeof value["has_more"] !== "boolean"
  )
    return null
  const name = nodeText(value["name"])
  const webUrl = nodeText(value["web_url"])
  if (name === null || webUrl === null) return null
  const matches: SharePointFindResults["matches"] = []
  for (const match of value["matches"]) {
    if (!isRecord(match) || !isNonNegativeInteger(match["offset"])) return null
    const excerpt = nodeText(match["excerpt"])
    if (excerpt === null || match["offset"] >= value["total_bytes"]) return null
    matches.push({ offset: match["offset"], excerpt })
  }
  return {
    hasMore: value["has_more"],
    limitReached: value["limit_reached"],
    matches,
    name,
    webUrl: safeHttpUrl(webUrl),
  }
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
