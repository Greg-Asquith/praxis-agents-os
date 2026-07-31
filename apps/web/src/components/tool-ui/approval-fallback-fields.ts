// apps/web/src/components/tool-ui/approval-fallback-fields.ts

import {
  scalarToolFieldDisplayValue,
  type ResolvedToolField,
  type ToolFieldDefinition,
} from "@/components/tool-ui/field-resolution"
import { humanizeKey } from "@/lib/format"
import { normalizeRecord } from "@/lib/guards"

export function approvalFallbackFields(
  source: unknown,
  declaredFields: Pick<ToolFieldDefinition, "key">[]
): ResolvedToolField[] {
  const normalized = normalizeRecord(source)
  if (!normalized) {
    return []
  }

  const declaredKeys = new Set(declaredFields.map((field) => field.key))
  return Object.entries(normalized).flatMap(([key, raw]): ResolvedToolField[] => {
    if (declaredKeys.has(key)) {
      return []
    }
    const scalarValue = scalarToolFieldDisplayValue(raw)
    if (scalarValue !== null) {
      return [{ key, label: humanizeKey(key), value: scalarValue, format: "text" }]
    }
    try {
      const value = JSON.stringify(raw, null, 2)
      return [{ key, label: humanizeKey(key), value, format: "multiline" }]
    } catch {
      return [{ key, label: humanizeKey(key), value: String(raw), format: "text" }]
    }
  })
}
