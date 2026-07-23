// apps/web/src/features/conversations/components/web-search-result.ts
import { safeHttpUrl } from "@/components/tool-ui/field-resolution"
import { nodeText } from "@/components/tool-ui/untrusted-node"
import { isRecord } from "@/lib/guards"

type WebSearchSource = {
  domain: string
  snippet: string | null
  title: string
  url: string
}

export type WebSearchResult = {
  model: string
  provider: string
  query: string
  sources: WebSearchSource[]
}

export function webSearchQuery(value: unknown): string | null {
  if (!isRecord(value)) {
    return null
  }
  return nonEmptyText(nodeText(value["query"]))
}

export function webSearchResult(value: unknown): WebSearchResult | null {
  if (!isRecord(value) || !Array.isArray(value["sources"])) {
    return null
  }
  const query = nonEmptyText(nodeText(value["query"]))
  const model = nonEmptyText(nodeText(value["model"]))
  const provider = nonEmptyText(nodeText(value["model_provider"]))
  if (query === null || model === null || provider === null) {
    return null
  }

  const sources: WebSearchSource[] = []
  for (const item of value["sources"]) {
    if (!isRecord(item)) {
      return null
    }
    const url = safeHttpUrl(item["url"])
    const rawTitle = item["title"]
    const rawSnippet = item["snippet"]
    const title = rawTitle === null || rawTitle === undefined ? null : nodeText(rawTitle)
    const snippet = rawSnippet === null || rawSnippet === undefined ? null : nodeText(rawSnippet)
    const invalidTitle = title === null && rawTitle !== null && rawTitle !== undefined
    const invalidSnippet = snippet === null && rawSnippet !== null && rawSnippet !== undefined
    if (url === null || invalidTitle || invalidSnippet) {
      return null
    }
    const domain = sourceDomain(url)
    if (domain === null) {
      return null
    }
    sources.push({
      domain,
      snippet: nonEmptyText(snippet),
      title: nonEmptyText(title) ?? domain,
      url,
    })
  }

  return { model, provider, query, sources }
}

function nonEmptyText(value: string | null): string | null {
  const normalized = value?.trim()
  if (!normalized) {
    return null
  }
  return normalized
}

function sourceDomain(url: string): string | null {
  try {
    return nonEmptyText(new URL(url).hostname.replace(/^www\./, ""))
  } catch {
    return null
  }
}
