// apps/web/src/features/conversations/components/approval-decision-fields.tsx

import { Field, FieldDescription, FieldLabel } from "@/components/ui/field"
import { Textarea } from "@/components/ui/textarea"

export function ApprovalOverrideInputField({
  id,
  onChange,
  value,
}: {
  id: string
  onChange: (value: string) => void
  value: string
}) {
  return (
    <details className="bg-muted/40 rounded-md p-3">
      <summary className="hover:text-foreground cursor-pointer text-sm font-medium">
        Advanced: Edit the Request
      </summary>
      <Field className="mt-3">
        <FieldLabel htmlFor={id}>Edited Request (JSON)</FieldLabel>
        <Textarea
          className="min-h-24 font-mono text-xs"
          id={id}
          onChange={(event) => {
            onChange(event.currentTarget.value)
          }}
          placeholder="Optional JSON object"
          value={value}
        />
        <FieldDescription>
          Leave blank to approve the request exactly as the agent sent it.
        </FieldDescription>
      </Field>
    </details>
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
        placeholder="For example: use the draft folder instead"
        value={value}
      />
    </Field>
  )
}
