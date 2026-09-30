// apps/web/src/features/conversations/native-tools/tool-search.ts

import { normalizeToolArgs } from "@/features/conversations/message-parts"
import { isRecord } from "@/lib/guards"

// Provider-native search runs as `tool_search`; the local fallback is `search_tools`.
const TOOL_SEARCH_TOOL_NAMES = new Set(["tool_search", "search_tools"])

export type ToolSearchResult = {
  toolNames: string[]
}

export function isToolSearchName(name: string) {
  return TOOL_SEARCH_TOOL_NAMES.has(name)
}

export function toolSearchQuery(args: unknown): string | null {
  const record = normalizeToolArgs(args)
  if (!isRecord(record) || !Array.isArray(record["queries"])) {
    return null
  }
  const queries = record["queries"]
    .filter((query): query is string => typeof query === "string")
    .map((query) => query.trim())
    .filter(Boolean)
  return queries.length > 0 ? queries.join(", ") : null
}

export function toolSearchResult(value: unknown): ToolSearchResult | null {
  const result = isRecord(value) && isRecord(value["return_value"]) ? value["return_value"] : value
  if (!isRecord(result) || !Array.isArray(result["discovered_tools"])) {
    return null
  }
  const toolNames = result["discovered_tools"].flatMap((match) =>
    isRecord(match) && typeof match["name"] === "string" ? [match["name"]] : []
  )
  return { toolNames: [...new Set(toolNames)] }
}
