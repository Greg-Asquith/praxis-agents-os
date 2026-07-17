// apps/web/src/features/conversations/tool-ui.ts

import type { ToolActivity } from "@/features/conversations/message-parts"
import { normalizeToolArgs } from "@/features/conversations/message-parts"
import type { ToolUi, ToolUiField, ToolUiFieldFormat } from "@/features/tools/types"
import { formatBytes, formatDateTime, truncateText } from "@/lib/format"
import { isRecord } from "@/lib/guards"

const TEMPLATE_VALUE_LIMIT = 64
const APPROVAL_PROMPT_VALUE_LIMIT = 240
const AUTO_FIELD_LIMIT = 6
const AUTO_VALUE_LIMIT = 200

export type ResolvedToolField = {
  key: string
  label: string
  value: string
  format: ToolUiFieldFormat
  items?: string[]
}

export function toolUiStatusLabel(ui: ToolUi, activity: ToolActivity): string | null {
  const template = statusTemplate(ui, activity.status)
  if (!template) {
    return null
  }
  return resolveToolTemplate(template, [normalizeToolArgs(activity.args), activity.result])
}

export function toolUiApprovalPrompt(ui: ToolUi, activity: ToolActivity): string | null {
  if (!ui.approval_prompt) {
    return null
  }
  return resolveToolTemplate(
    ui.approval_prompt,
    [normalizeToolArgs(activity.args)],
    APPROVAL_PROMPT_VALUE_LIMIT
  )
}

export function resolveToolTemplate(
  template: string,
  sources: unknown[],
  valueLimit = TEMPLATE_VALUE_LIMIT
): string | null {
  const missing: string[] = []
  const resolved = template.replace(/\{([a-z0-9_]+)\}/gi, (_match, key: string) => {
    const value = lookupTemplateValue(key, sources)
    if (value === null) {
      missing.push(key)
      return ""
    }
    return truncateText(value, valueLimit, "…")
  })
  return missing.length > 0 ? null : resolved
}

export function resolveUiFields(fields: ToolUiField[], source: unknown): ResolvedToolField[] {
  const record = normalizeToolArgs(source)
  if (!isRecord(record)) {
    return []
  }
  const resolved: ResolvedToolField[] = []
  for (const field of fields) {
    const value = displayValue(record[field.key], field.format)
    if (value !== null) {
      const baseField = { key: field.key, label: field.label, value, format: field.format }
      const items = field.format === "list" ? listItems(record[field.key]) : null
      resolved.push(items === null ? baseField : { ...baseField, items })
    }
  }
  return resolved
}

export function editableUiFields(fields: ToolUiField[], source: unknown): ToolUiField[] {
  const record = normalizeToolArgs(source)
  if (!isRecord(record)) {
    return []
  }
  return fields.filter((field) => field.editable && typeof record[field.key] === "string")
}

export function autoUiFields(source: unknown): ResolvedToolField[] {
  const normalized = normalizeToolArgs(source)
  if (!isRecord(normalized)) {
    return []
  }
  const resolved: ResolvedToolField[] = []
  for (const [key, raw] of Object.entries(normalized)) {
    if (resolved.length >= AUTO_FIELD_LIMIT) {
      break
    }
    const value = scalarDisplayValue(raw)
    if (value !== null) {
      resolved.push({
        key,
        label: humanizeKey(key),
        value: truncateText(value, AUTO_VALUE_LIMIT, "…"),
        format: "text",
      })
    }
  }
  return resolved
}

export function friendlyResultText(result: unknown): string | null {
  if (typeof result !== "string") {
    return null
  }
  const trimmed = result.trim()
  if (!trimmed || trimmed.startsWith("{") || trimmed.startsWith("[")) {
    return null
  }
  return truncateText(trimmed, 2000, "…")
}

export function shortOutcomeMetric(fields: ResolvedToolField[], maxLength = 40): string | null {
  const value = fields[0]?.value.replace(/\s+/g, " ").trim()
  return value && value.length <= maxLength ? value : null
}

export function humanizeKey(key: string): string {
  const spaced = key
    .replace(/[_-]+/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .trim()
  if (!spaced) {
    return key
  }
  return spaced.charAt(0).toUpperCase() + spaced.slice(1).toLowerCase()
}

function statusTemplate(ui: ToolUi, status: ToolActivity["status"]): string {
  if (status === "running") {
    return ui.running_label
  }
  if (status === "completed") {
    return ui.completed_label
  }
  if (status === "failed") {
    return ui.failed_label
  }
  return ""
}

function lookupTemplateValue(key: string, sources: unknown[]): string | null {
  for (const source of sources) {
    if (!isRecord(source)) {
      continue
    }
    const value = scalarDisplayValue(source[key])
    if (value !== null) {
      return value
    }
  }
  return null
}

function displayValue(value: unknown, format: ToolUiFieldFormat): string | null {
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
    const items = listItems(value)
    return items && items.length > 0 ? items.join(", ") : null
  }
  return scalarDisplayValue(value)
}

function safeHttpUrl(value: unknown): string | null {
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

function listItems(value: unknown): string[] | null {
  if (
    !Array.isArray(value) ||
    !value.every((item) => typeof item === "string" || typeof item === "number")
  ) {
    return null
  }
  return value.map(String)
}

function scalarDisplayValue(value: unknown): string | null {
  if (typeof value === "string") {
    return value.trim() ? value : null
  }
  if (typeof value === "number") {
    return String(value)
  }
  if (typeof value === "boolean") {
    return value ? "Yes" : "No"
  }
  return null
}
