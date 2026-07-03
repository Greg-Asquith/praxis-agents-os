// apps/web/src/features/agents/components/agent-tool-catalog-utils.ts

import type { RuntimeToolMode } from "@/features/agents/runtime-tools"
import type { ToolCatalogEntry } from "@/features/tools/types"
import { titleCaseToken } from "@/lib/format"

export const ALL_TOOL_PROVIDERS_VALUE = "__all__"
export const UNAVAILABLE_TOOL_PROVIDER_VALUE = "unavailable"

export type ToolGroup = {
  provider: string
  tools: ToolCatalogEntry[]
}

export function groupToolsByProvider(tools: ToolCatalogEntry[]): ToolGroup[] {
  const groups = new Map<string, ToolCatalogEntry[]>()
  for (const tool of tools) {
    groups.set(tool.provider, [...(groups.get(tool.provider) ?? []), tool])
  }
  return [...groups.entries()]
    .map(([provider, providerTools]) => ({
      provider,
      tools: providerTools.toSorted((left, right) =>
        left.label.localeCompare(right.label, undefined, { sensitivity: "base" })
      ),
    }))
    .toSorted((left, right) =>
      titleCaseToken(left.provider, left.provider).localeCompare(
        titleCaseToken(right.provider, right.provider),
        undefined,
        { sensitivity: "base" }
      )
    )
}

export function providerFilterOptions(tools: ToolCatalogEntry[]) {
  const providerNames = new Map<string, string>()
  for (const tool of tools) {
    providerNames.set(tool.provider, titleCaseToken(tool.provider, tool.provider))
  }
  const options = [...providerNames.entries()]
    .map(([value, label]) => ({ value, label }))
    .toSorted((left, right) =>
      left.label.localeCompare(right.label, undefined, { sensitivity: "base" })
    )
  return [{ value: ALL_TOOL_PROVIDERS_VALUE, label: "All providers" }, ...options]
}

export function filterTools(
  tools: ToolCatalogEntry[],
  providerFilter: string,
  normalizedSearch: string
) {
  return tools.filter((tool) => {
    const matchesProvider =
      providerFilter === ALL_TOOL_PROVIDERS_VALUE || tool.provider === providerFilter
    if (!matchesProvider) {
      return false
    }
    if (!normalizedSearch) {
      return true
    }
    const providerLabel = titleCaseToken(tool.provider, tool.provider)
    return [tool.name, tool.label, tool.description, providerLabel].some((value) =>
      value.toLowerCase().includes(normalizedSearch)
    )
  })
}

export function stripProviderPrefix(label: string, providerLabel: string) {
  const lowerLabel = label.toLowerCase()
  const lowerProvider = providerLabel.toLowerCase()
  if (!lowerLabel.startsWith(lowerProvider)) {
    return label
  }

  const stripped = label
    .slice(providerLabel.length)
    .replace(/^\s*[-:]\s*/, "")
    .trim()
  return stripped || label
}

export function unavailableModeOptions(mode: RuntimeToolMode | undefined): RuntimeToolMode[] {
  if (mode === "approval" || mode === "auto") {
    return ["off", mode]
  }
  return ["off"]
}
