// apps/web/src/features/conversations/components/approval-decision-fields.tsx

import type { ChangeEvent } from "react"

import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  toolFieldLabelClass,
  toolFieldWellClass,
} from "@/features/conversations/components/tool-field"
import { normalizeToolArgs } from "@/features/conversations/message-parts"
import type { ToolUiField } from "@/features/tools/types"
import { isRecord } from "@/lib/guards"
import { cn } from "@/lib/utils"

export function ApprovalEditableFields({
  activityId,
  args,
  disabled,
  edits,
  fields,
  onChange,
}: {
  activityId: string
  args: unknown
  disabled: boolean
  edits: Record<string, string>
  fields: ToolUiField[]
  onChange: (key: string, value: string) => void
}) {
  const record = normalizeToolArgs(args)
  if (!isRecord(record) || fields.length === 0) {
    return null
  }

  return (
    <FieldGroup className="gap-3">
      {fields.map((field) => {
        const originalValue = record[field.key]
        if (typeof originalValue !== "string") {
          return null
        }
        const id = `${activityId}-${field.key}-edit`
        const inputProps = {
          disabled,
          id,
          onChange: (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
            onChange(field.key, event.currentTarget.value)
          },
          placeholder: field.placeholder || undefined,
          value: edits[field.key] ?? originalValue,
        }
        return (
          <Field className="gap-1" data-disabled={disabled} key={field.key}>
            <FieldLabel className={toolFieldLabelClass} htmlFor={id}>
              {field.label}
            </FieldLabel>
            {field.format === "multiline" ? (
              <Textarea className={cn(toolFieldWellClass, "min-h-20")} {...inputProps} />
            ) : (
              <Input className={toolFieldWellClass} {...inputProps} />
            )}
          </Field>
        )
      })}
    </FieldGroup>
  )
}

export function ApprovalDenialMessageField({
  id,
  onChange,
  value,
}: {
  id: string
  onChange: (value: string) => void
  value: string
}) {
  return (
    <Field>
      <FieldLabel htmlFor={id}>Tell the agent why (optional)</FieldLabel>
      <Textarea
        className="min-h-20"
        id={id}
        onChange={(event) => {
          onChange(event.currentTarget.value)
        }}
        placeholder="For example: search for UK pricing instead"
        value={value}
      />
    </Field>
  )
}
