// apps/web/src/integrations/ads/lib/keyword-notation.ts

export type KeywordMatchType = "EXACT" | "PHRASE" | "BROAD"
export type PastedKeyword = { matchType: KeywordMatchType; text: string }

/** Reads one keyword per line: `[exact]`, `"phrase"`, or plain text for broad. */
export function parseKeywordLines(value: string): PastedKeyword[] {
  return value.split(/\r?\n/).flatMap((line): PastedKeyword[] => {
    const trimmed = line.trim()
    if (!trimmed) return []
    const exact = /^\[(.+)\]$/.exec(trimmed)
    if (exact?.[1]) return [{ matchType: "EXACT", text: collapse(exact[1]) }]
    const phrase = /^"(.+)"$/.exec(trimmed)
    if (phrase?.[1]) return [{ matchType: "PHRASE", text: collapse(phrase[1]) }]
    return [{ matchType: "BROAD", text: collapse(trimmed) }]
  })
}

function collapse(text: string): string {
  return text.trim().split(/\s+/).join(" ")
}

export function formatKeywordLine({ matchType, text }: PastedKeyword): string {
  if (matchType === "EXACT") return `[${text}]`
  if (matchType === "PHRASE") return `"${text}"`
  return text
}

export function matchTypeCounts(keywords: readonly PastedKeyword[]): {
  broad: number
  exact: number
  phrase: number
} {
  const count = (matchType: KeywordMatchType) =>
    keywords.filter((keyword) => keyword.matchType === matchType).length
  return { broad: count("BROAD"), exact: count("EXACT"), phrase: count("PHRASE") }
}
