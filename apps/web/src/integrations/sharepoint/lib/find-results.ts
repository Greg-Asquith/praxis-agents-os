// apps/web/src/integrations/sharepoint/lib/find-results.ts

import { safeHttpUrl } from "@/components/tool-ui/field-resolution"
import { nodeText } from "@/components/tool-ui/untrusted-node"
import { parseTextMatches, type TextMatches } from "@/integrations/text-matches"
import { isRecord } from "@/lib/guards"

export type SharePointFindResults = TextMatches & {
  limitReached: boolean
  name: string
  webUrl: string | null
}

export function parseFindResults(value: unknown): SharePointFindResults | null {
  if (!isRecord(value) || typeof value["limit_reached"] !== "boolean") return null
  const found = parseTextMatches(value)
  const name = nodeText(value["name"])
  const webUrl = nodeText(value["web_url"])
  if (found === null || name === null || webUrl === null) return null
  return { ...found, limitReached: value["limit_reached"], name, webUrl: safeHttpUrl(webUrl) }
}
