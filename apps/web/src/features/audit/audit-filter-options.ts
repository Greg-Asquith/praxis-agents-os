// apps/web/src/features/audit/audit-filter-options.ts

import type { ToolCatalogEntry } from "@/features/tools/types"
import { titleCaseToken } from "@/lib/format"

export type AuditFilterOption = {
  label: string
  value: string
}

export function auditToolFilterOptions(tools: ToolCatalogEntry[]): AuditFilterOption[] {
  const options = new Map<string, AuditFilterOption>()
  for (const tool of tools) {
    if (!options.has(tool.name)) {
      options.set(tool.name, { label: tool.label, value: tool.name })
    }
  }
  return [...options.values()].toSorted(compareFilterOptions)
}

export function auditProviderFilterOptions(tools: ToolCatalogEntry[]): AuditFilterOption[] {
  const options = new Map<string, AuditFilterOption>()
  for (const tool of tools) {
    if (!options.has(tool.provider)) {
      options.set(tool.provider, {
        label: titleCaseToken(tool.provider, tool.provider),
        value: tool.provider,
      })
    }
  }
  return [...options.values()].toSorted(compareFilterOptions)
}

function compareFilterOptions(left: AuditFilterOption, right: AuditFilterOption) {
  return (
    left.label.localeCompare(right.label, undefined, { sensitivity: "base" }) ||
    left.value.localeCompare(right.value)
  )
}
