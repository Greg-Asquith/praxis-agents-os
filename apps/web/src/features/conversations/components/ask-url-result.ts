// apps/web/src/features/conversations/components/ask-url-result.ts

import { safeHttpUrl } from "@/components/tool-ui/field-resolution"
import { nodeText } from "@/components/tool-ui/untrusted-node"
import { urlDomain } from "@/lib/format"
import { isRecord } from "@/lib/guards"

export const ASK_URL_TOOL_NAME = "ask_url"

type AskUrlSource = {
  domain: string
  title: string
  url: string
}

export type AskUrlResult = {
  answer: string
  model: string
  provider: string
  question: string
  sources: AskUrlSource[]
  url: string
}

export function askUrlUrl(value: unknown): string | null {
  if (!isRecord(value)) {
    return null
  }
  return safeHttpUrl(nodeText(value["url"]))
}

export function askUrlResult(value: unknown): AskUrlResult | null {
  if (!isRecord(value) || !Array.isArray(value["sources"])) {
    return null
  }
  const url = safeHttpUrl(nodeText(value["url"]))
  const answer = nonEmptyText(nodeText(value["answer"]))
  const question = nonEmptyText(nodeText(value["question"]))
  const model = nonEmptyText(nodeText(value["model"]))
  const provider = nonEmptyText(nodeText(value["provider"]))
  if (url === null || answer === null || question === null || model === null || provider === null) {
    return null
  }

  const sources: AskUrlSource[] = []
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
    const domain = urlDomain(sourceUrl)
    if (domain === null) {
      return null
    }
    sources.push({ domain, title: nonEmptyText(title) ?? domain, url: sourceUrl })
  }

  return { answer, model, provider, question, sources, url }
}

function nonEmptyText(value: string | null): string | null {
  const normalized = value?.trim()
  if (!normalized) {
    return null
  }
  return normalized
}
