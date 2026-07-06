// apps/web/src/features/conversations/tool-ui.ts

import type { ToolActivity } from "@/features/conversations/message-parts"
import { normalizeToolArgs } from "@/features/conversations/message-parts"
import type { ToolUi, ToolUiField, ToolUiFieldFormat } from "@/features/tools/types"
import { formatBytes, formatDateTime } from "@/lib/format"

const TEMPLATE_VALUE_LIMIT = 64
const AUTO_FIELD_LIMIT = 6
const AUTO_VALUE_LIMIT = 200

export type ResolvedToolField = {
  key: string
  label: string
  value: string
  format: ToolUiFieldFormat
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
  return resolveToolTemplate(ui.approval_prompt, [normalizeToolArgs(activity.args)])
}

export function resolveToolTemplate(template: string, sources: unknown[]): string | null {
  const missing: string[] = []
  const resolved = template.replace(/\{([a-z0-9_]+)\}/gi, (_match, key: string) => {
    const value = lookupTemplateValue(key, sources)
    if (value === null) {
      missing.push(key)
      return ""
    }
    return truncate(value, TEMPLATE_VALUE_LIMIT)
  })
  return missing.length > 0 ? null : resolved
}

export function resolveUiFields(fields: ToolUiField[], source: unknown): ResolvedToolField[] {
  const record = asRecord(normalizeToolArgs(source))
  if (!record) {
    return []
  }
  const resolved: ResolvedToolField[] = []
  for (const field of fields) {
    const value = displayValue(record[field.key], field.format)
    if (value !== null) {
      resolved.push({ key: field.key, label: field.label, value, format: field.format })
    }
  }
  return resolved
}

export function autoUiFields(source: unknown): ResolvedToolField[] {
  const normalized = normalizeToolArgs(source)
  const record = asRecord(normalized)
  if (!record) {
    return []
  }
  const resolved: ResolvedToolField[] = []
  for (const [key, raw] of Object.entries(record)) {
    if (resolved.length >= AUTO_FIELD_LIMIT) {
      break
    }
    const value = scalarDisplayValue(raw)
    if (value !== null) {
      resolved.push({
        key,
        label: humanizeKey(key),
        value: truncate(value, AUTO_VALUE_LIMIT),
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
  return truncate(trimmed, 2000)
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
    const record = asRecord(source)
    if (!record) {
      continue
    }
    const value = scalarDisplayValue(record[key])
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
  return scalarDisplayValue(value)
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

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null
  }
  return value as Record<string, unknown>
}

function truncate(value: string, limit: number): string {
  return value.length > limit ? `${value.slice(0, limit)}…` : value
}
