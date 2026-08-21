// apps/web/src/features/conversations/components/web-fetch-results.ts

import { safeHttpUrl } from "@/components/tool-ui/field-resolution"
import { nodeText } from "@/components/tool-ui/untrusted-node"
import { isRecord } from "@/lib/guards"

export const WEB_FETCH_TOOL_NAME = "fetch_url"

type WebFetchSource = {
  domain: string
  title: string
  url: string
}

export type WebFetchResult = {
  content: string
  model: string
  provider: string
  sources: WebFetchSource[]
  url: string
}

export function webFetchUrl(value: unknown): string | null {
  if (!isRecord(value)) {
    return null
  }
  return safeHttpUrl(nodeText(value["url"]))
}

export function webFetchResult(value: unknown): WebFetchResult | null {
  if (!isRecord(value) || !Array.isArray(value["sources"])) {
    return null
  }
  const url = safeHttpUrl(nodeText(value["url"]))
  const content = nonEmptyText(nodeText(value["content"]))
  const model = nonEmptyText(nodeText(value["model"]))
  const provider = nonEmptyText(nodeText(value["model_provider"]))
  if (url === null || content === null || model === null || provider === null) {
    return null
  }

  const sources: WebFetchSource[] = []
  for (const item of value["sources"]) {
    if (!isRecord(item)) {
      return null
    }
    const sourceUrl = safeHttpUrl(item["url"])
    if (sourceUrl === null) {
      return null
    }
    const rawTitle = item["title"]
    const title = rawTitle === null || rawTitle === undefined ? null : nodeText(rawTitle)
    if (title === null && rawTitle !== null && rawTitle !== undefined) {
      return null
    }
    const domain = sourceDomain(sourceUrl)
    if (domain === null) {
      return null
    }
    sources.push({ domain, title: nonEmptyText(title) ?? domain, url: sourceUrl })
  }

  return { content, model, provider, sources, url }
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
