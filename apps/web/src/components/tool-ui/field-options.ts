// apps/web/src/components/tool-ui/field-options.ts

import type { ApprovalField } from "@/components/tool-ui/approval-types"
import type { EditedValues } from "@/components/tool-ui/edited-values"

export function availableFieldOptions(
  field: ApprovalField,
  args: Record<string, unknown>,
  fields: ApprovalField[]
): string[] {
  if (!field.options_by_field) return field.options
  const parentValue = args[field.options_by_field]
  if (typeof parentValue === "string" && parentValue) {
    return field.options_by_value?.[parentValue] ?? []
  }
  const parentOptions = fields.find((candidate) => candidate.key === field.options_by_field)?.options
  if (!parentOptions?.length) return []
  return field.options.filter((option) =>
    parentOptions.every((value) => field.options_by_value?.[value]?.includes(option))
  )
}

export function reconcileFieldOptionEdits(
  fields: ApprovalField[],
  args: Record<string, unknown>,
  edits: EditedValues,
  changedKey: string
): EditedValues {
  const next = { ...edits }
  const effective = { ...args, ...edits }
  for (const field of fields) {
    if (!field.editable || field.options_by_field !== changedKey) continue
    const value = effective[field.key]
    if (value == null || value === "") continue
    const options = availableFieldOptions(field, effective, fields)
    if (typeof value === "string" && !options.includes(value) && options[0]) {
      next[field.key] = options[0]
    }
  }
  return next
}

export function fieldOptionsError(
  fields: ApprovalField[],
  args: Record<string, unknown>
): string | null {
  for (const field of fields) {
    if (!field.editable || !field.options_by_field) continue
    const value = args[field.key]
    if (value == null || value === "") continue
    if (typeof value !== "string" || !availableFieldOptions(field, args, fields).includes(value)) {
      return `Choose an available option for ${field.label}.`
    }
  }
  return null
}
