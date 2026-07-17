// apps/web/src/features/conversations/components/approval-decision-fields.tsx

import { useCallback, useRef, useState, type ChangeEvent } from "react"

import { Button } from "@/components/ui/button"
import { Field, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import type { LocalApprovalDecision } from "@/features/conversations/approval-decisions"
import { ToolField } from "@/features/conversations/components/tool-field"
import {
  toolFieldLabelClass,
  toolFieldWellClass,
} from "@/features/conversations/components/tool-field"
import { normalizeToolArgs } from "@/features/conversations/message-parts"
import type { ResolvedToolField } from "@/features/conversations/tool-ui"
import { resolveUiFields } from "@/features/conversations/tool-ui"
import type { ToolUiField } from "@/features/tools/types"
import { titleCaseToken } from "@/lib/format"
import { isRecord } from "@/lib/guards"
import { cn } from "@/lib/utils"

export function ApprovalRequestFields({
  activityId,
  args,
  decision,
  disabled,
  fallbackFields,
  fields,
  onEditsChange,
}: {
  activityId: string
  args: unknown
  decision: LocalApprovalDecision
  disabled: boolean
  fallbackFields: ResolvedToolField[]
  fields: ToolUiField[]
  onEditsChange: (edits: Record<string, string>) => void
}) {
  const [revealedFields, setRevealedFields] = useState<Set<string>>(() => new Set())
  const focusFieldKey = useRef<string | null>(null)
  const record = normalizeToolArgs(args)

  if (fields.length === 0 || !isRecord(record)) {
    return fallbackFields.length > 0 ? (
      <div className="grid min-w-0 gap-3">
        {fallbackFields.map((field) => (
          <ToolField field={field} key={field.key} />
        ))}
      </div>
    ) : null
  }

  const lockedRecord = { ...record, ...decision.edits }

  return (
    <div className="grid min-w-0 gap-3">
      {fields.map((field) => {
        const rawValue = record[field.key]
        const originalValue = typeof rawValue === "string" ? rawValue : null
        const editable = field.editable && originalValue !== null
        const value = originalValue === null ? "" : (decision.edits[field.key] ?? originalValue)
        const isEmptySecondary = field.secondary && !value.trim()
        const isRevealed = revealedFields.has(field.key)

        if (decision.decision !== "pending") {
          const resolved = resolveUiFields([field], lockedRecord)[0]
          return resolved ? <ToolField field={resolved} key={field.key} /> : null
        }

        if (field.secondary && rawValue == null && !editable) {
          return null
        }

        if (isEmptySecondary && !isRevealed) {
          return editable ? (
            <Button
              className="text-muted-foreground w-fit px-0"
              disabled={disabled}
              key={field.key}
              onClick={() => {
                focusFieldKey.current = field.key
                setRevealedFields((current) => new Set(current).add(field.key))
              }}
              size="sm"
              type="button"
              variant="ghost"
            >
              + Add {field.label}
            </Button>
          ) : null
        }

        if (editable) {
          const id = `${activityId}-${field.key}-edit`
          const focusRef = (node: HTMLElement | null) => {
            if (node && focusFieldKey.current === field.key) {
              focusFieldKey.current = null
              node.focus()
            }
          }
          const clearSecondary =
            field.secondary && isRevealed ? (
              <Button
                className="h-auto px-1 py-0 text-xs"
                disabled={disabled}
                onClick={() => {
                  const nextEdits = Object.fromEntries(
                    Object.entries(decision.edits).filter(([key]) => key !== field.key)
                  )
                  onEditsChange(nextEdits)
                  setRevealedFields((current) => {
                    const next = new Set(current)
                    next.delete(field.key)
                    return next
                  })
                }}
                size="sm"
                type="button"
                variant="ghost"
              >
                Remove
              </Button>
            ) : null

          return (
            <Field className="gap-1" data-disabled={disabled} key={field.key}>
              <div className="flex items-center justify-between gap-2">
                <FieldLabel className={toolFieldLabelClass} htmlFor={id}>
                  {field.label}
                </FieldLabel>
                {clearSecondary}
              </div>
              {field.options.length > 0 ? (
                <Select<string>
                  disabled={disabled}
                  onValueChange={(nextValue) => {
                    if (nextValue !== null) {
                      onEditsChange({ ...decision.edits, [field.key]: nextValue })
                    }
                  }}
                  value={value}
                >
                  <SelectTrigger className={cn(toolFieldWellClass, "h-8")} id={id} ref={focusRef}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent align="start">
                    <SelectGroup>
                      {field.options.map((option) => {
                        const label = titleCaseToken(option, option)
                        return (
                          <SelectItem key={option} label={label} value={option}>
                            {label}
                          </SelectItem>
                        )
                      })}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              ) : field.format === "multiline" || value.length > 80 ? (
                <Textarea
                  className={cn(toolFieldWellClass, "min-h-16")}
                  disabled={disabled}
                  id={id}
                  onChange={changeHandler(field.key, decision.edits, onEditsChange)}
                  placeholder={field.placeholder || undefined}
                  ref={focusRef}
                  value={value}
                />
              ) : (
                <Input
                  className={toolFieldWellClass}
                  disabled={disabled}
                  id={id}
                  onChange={changeHandler(field.key, decision.edits, onEditsChange)}
                  placeholder={field.placeholder || undefined}
                  ref={focusRef}
                  value={value}
                />
              )}
            </Field>
          )
        }

        const resolved = resolveUiFields([field], record)[0]
        return resolved ? <ToolField field={resolved} key={field.key} /> : null
      })}
    </div>
  )
}

export function ApprovalDenialMessageField({
  disabled,
  id,
  onChange,
  value,
}: {
  disabled: boolean
  id: string
  onChange: (value: string) => void
  value: string
}) {
  const didFocus = useRef(false)
  const focusOnMount = useCallback((node: HTMLTextAreaElement | null) => {
    if (node && !didFocus.current) {
      didFocus.current = true
      node.focus()
    }
  }, [])

  return (
    <Field>
      <FieldLabel htmlFor={id}>Tell the agent why (optional)</FieldLabel>
      <Textarea
        className="min-h-20"
        disabled={disabled}
        id={id}
        onChange={(event) => {
          onChange(event.currentTarget.value)
        }}
        placeholder="For example: search for UK pricing instead"
        ref={focusOnMount}
        value={value}
      />
    </Field>
  )
}

function changeHandler(
  key: string,
  edits: Record<string, string>,
  onEditsChange: (edits: Record<string, string>) => void
) {
  return (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    onEditsChange({ ...edits, [key]: event.currentTarget.value })
  }
}
