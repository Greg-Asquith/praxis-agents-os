// apps/web/src/components/tool-ui/field-edit-values.ts

import type { ApprovalField } from "@/components/tool-ui/approval-types"
import type { EditedScalar } from "@/components/tool-ui/edited-values"

export const NO_CHANGE = Symbol("no-change")
export const INVALID_EDIT = Symbol("invalid-edit")

export function isEditedScalar(value: unknown): value is EditedScalar {
  return typeof value === "string" || typeof value === "boolean" || isFiniteNumber(value)
}

export function isStringList(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string")
}

function isOptionalBoolean(field: ApprovalField | undefined, value: unknown): boolean {
  return value == null && field?.format === "boolean" && field.secondary && field.editable
}

export function isScalarOrListField(field: ApprovalField): boolean {
  return [
    "text",
    "multiline",
    "markdown",
    "html",
    "datetime",
    "boolean",
    "number",
    "list",
  ].includes(field.format)
}

export function editableScalarOrListValue(
  field: ApprovalField,
  value: unknown
): EditedScalar | string[] | null {
  if (field.format === "boolean") {
    if (isOptionalBoolean(field, value)) return ""
    return typeof value === "boolean" ? value : null
  }
  if (field.format === "number") return isFiniteNumber(value) ? value : null
  if (field.format === "list") {
    if (value == null && field.secondary) return []
    return isStringList(value) ? [...value] : null
  }
  if (value == null && field.editable && field.options.length > 0) return ""
  return typeof value === "string" ? value : null
}

export function mergeScalarEdit(
  original: unknown,
  edit: EditedScalar,
  field?: ApprovalField
): unknown {
  if (typeof edit === "string") return mergeStringEdit(original, edit, field)
  if (typeof edit === "boolean") {
    if (isOptionalBoolean(field, original)) return edit
    if (typeof original !== "boolean") return INVALID_EDIT
    return edit === original ? NO_CHANGE : edit
  }
  if (!isFiniteNumber(original) || !Number.isFinite(edit)) return INVALID_EDIT
  if (Number.isInteger(original) && !Number.isInteger(edit)) return INVALID_EDIT
  return Object.is(edit, original) ? NO_CHANGE : edit
}

export function mergeListEdit(original: unknown, edit: unknown[], field?: ApprovalField): unknown {
  if (!isStringList(edit)) return INVALID_EDIT
  if (original == null && field?.format === "list" && field.secondary) return edit
  if (!isStringList(original)) return INVALID_EDIT
  return edit.length === original.length && edit.every((item, index) => item === original[index])
    ? NO_CHANGE
    : edit
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value)
}

function mergeStringEdit(original: unknown, edit: string, field?: ApprovalField): unknown {
  if (original == null && field?.editable && field.options.includes(edit)) return edit
  if (typeof original !== "string") return INVALID_EDIT
  if (field) return edit === original ? NO_CHANGE : edit
  const trimmedEdit = edit.trim()
  const trimmedOriginal = original.trim()
  return trimmedEdit === trimmedOriginal || (!trimmedEdit && trimmedOriginal)
    ? NO_CHANGE
    : trimmedEdit
}
