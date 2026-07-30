// apps/web/src/features/conversations/tool-ui.ts

import {
  resolveToolFields,
  scalarToolFieldDisplayValue,
  type ResolvedToolField,
} from "@/components/tool-ui/field-resolution"
import { nodeText } from "@/components/tool-ui/untrusted-node"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { normalizeToolArgs } from "@/features/conversations/message-parts"
import type { ToolUi, ToolUiField } from "@/features/tools/types"
import { truncateText } from "@/lib/format"
import { isRecord } from "@/lib/guards"

const TEMPLATE_VALUE_LIMIT = 64
const APPROVAL_PROMPT_VALUE_LIMIT = 240
const AUTO_FIELD_LIMIT = 6
const AUTO_VALUE_LIMIT = 200

export type { ResolvedToolField } from "@/components/tool-ui/field-resolution"

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
  return resolveToolFields(fields, record)
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
    const value = scalarToolFieldDisplayValue(raw)
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

export function approvalFallbackFields(
  source: unknown,
  declaredFields: ToolUiField[]
): ResolvedToolField[] {
  const normalized = normalizeToolArgs(source)
  if (!isRecord(normalized)) {
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

export function friendlyResultText(result: unknown): string | null {
  const text = nodeText(result)
  if (text === null) {
    return null
  }
  const trimmed = text.trim()
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
    const value = scalarToolFieldDisplayValue(source[key])
    if (value !== null) {
      return value
    }
  }
  return null
}
