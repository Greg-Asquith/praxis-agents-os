// apps/web/src/components/tool-ui/field-resolution.ts

import { nodeText } from "@/components/tool-ui/untrusted-node"
import { formatBytes, formatDateTime } from "@/lib/format"

export type ToolFieldFormat =
  "text" | "multiline" | "markdown" | "bytes" | "datetime" | "boolean" | "url" | "list"

export type ToolFieldDefinition = {
  format: ToolFieldFormat
  key: string
  label: string
}

export type ResolvedToolField = {
  format: ToolFieldFormat
  items?: string[]
  key: string
  label: string
  value: string
}

export function resolveToolField(
  field: ToolFieldDefinition,
  value: unknown
): ResolvedToolField | null {
  const resolved = toolFieldDisplayValue(value, field.format)
  if (resolved === null) {
    return null
  }

  const baseField = { key: field.key, label: field.label, value: resolved, format: field.format }
  const items = field.format === "list" ? toolFieldListItems(value) : null
  return items === null ? baseField : { ...baseField, items }
}

export function resolveToolFields(
  fields: ToolFieldDefinition[],
  source: Record<string, unknown>
): ResolvedToolField[] {
  return fields.flatMap((field) => {
    const resolved = resolveToolField(field, source[field.key])
    return resolved ? [resolved] : []
  })
}

export function scalarToolFieldDisplayValue(value: unknown): string | null {
  const text = nodeText(value)
  if (text !== null) {
    return text.trim() ? text : null
  }
  if (typeof value === "number") {
    return String(value)
  }
  if (typeof value === "boolean") {
    return value ? "Yes" : "No"
  }
  return null
}

function toolFieldDisplayValue(value: unknown, format: ToolFieldFormat): string | null {
  if (value === undefined || value === null) {
    return null
  }
  if (format === "bytes" && typeof value === "number") {
    return formatBytes(value)
  }
  if (format === "datetime" && typeof value === "string") {
    return formatDateTime(value)
  }
  if (format === "boolean") {
    return value === true ? "Yes" : value === false ? "No" : null
  }
  if (format === "url") {
    return safeHttpUrl(value)
  }
  if (format === "list") {
    const items = toolFieldListItems(value)
    return items && items.length > 0 ? items.join(", ") : null
  }
  return scalarToolFieldDisplayValue(value)
}

export function safeHttpUrl(value: unknown): string | null {
  if (typeof value !== "string") {
    return null
  }
  const normalized = value.trim()
  if (!normalized) {
    return null
  }
  try {
    const url = new URL(normalized)
    return url.protocol === "http:" || url.protocol === "https:" ? normalized : null
  } catch {
    return null
  }
}

function toolFieldListItems(value: unknown): string[] | null {
  if (!Array.isArray(value)) {
    return null
  }
  const items: string[] = []
  for (const item of value) {
    const text = nodeText(item)
    if (text !== null) {
      items.push(text)
    } else if (typeof item === "number") {
      items.push(String(item))
    } else {
      return null
    }
  }
  return items
}
