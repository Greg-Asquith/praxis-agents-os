// apps/web/src/components/tool-ui/approval-request-fields.tsx

import { use, useEffect, useRef, useState, type ChangeEvent } from "react"
import { ChevronDownIcon } from "lucide-react"

import { ApprovalStaticField } from "@/components/tool-ui/approval-static-field"
import { EntityFieldInput } from "@/components/tool-ui/entity-field-input"
import type {
  ApprovalDecision,
  ApprovalFallbackField,
  ApprovalField,
} from "@/components/tool-ui/approval-types"
import type { EditedKeyValue, EditedValue, EditedValues } from "@/components/tool-ui/edited-values"
import { resolveToolField, type ToolFieldFormat } from "@/components/tool-ui/field-resolution"
import { fieldLabelClass, fieldWellClass } from "@/components/tool-ui/field-styles"
import { KeyValueFieldInput } from "@/components/tool-ui/keyvalue-field-input"
import { ListFieldInput } from "@/components/tool-ui/list-field-input"
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
import { titleCaseToken } from "@/lib/format"
import { isRecord } from "@/lib/guards"
import { cn } from "@/lib/utils"
import { ToolConversationContext } from "@/components/tool-ui/tool-conversation-context"

const NOOP_ENTITY_VALIDITY = () => undefined

export function ApprovalRequestFields({
  activityId,
  args,
  decision,
  disabled,
  fallbackFields,
  fields,
  onEditsChange,
  onEntityValidityChange = NOOP_ENTITY_VALIDITY,
  toolName = "",
}: {
  activityId: string
  args: unknown
  decision: ApprovalDecision
  disabled: boolean
  fallbackFields: ApprovalFallbackField[]
  fields: ApprovalField[]
  onEditsChange: (edits: EditedValues) => void
  onEntityValidityChange?: (key: string, valid: boolean) => void
  toolName?: string
}) {
  const [revealedFields, setRevealedFields] = useState<Set<string>>(() => new Set())
  const [clearedEntityFields, setClearedEntityFields] = useState<Set<string>>(() => new Set())
  const focusFieldKey = useRef<string | null>(null)
  const conversationId = use(ToolConversationContext)

  if (fields.length === 0 || !isRecord(args)) {
    return fallbackFields.length > 0 ? (
      <div className="grid min-w-0 gap-3 sm:grid-flow-dense sm:grid-cols-2">
        {fallbackFields.map((field) => (
          <div className={fieldSpanClass(field.format)} key={field.key}>
            <ApprovalStaticField field={field} />
          </div>
        ))}
      </div>
    ) : null
  }

  const lockedRecord = resolveLockedRecord(args, decision.edits)
  const applyFieldEdit = (key: string, nextValue: EditedValue) => {
    const dependentKeys = new Set(
      fields
        .filter((candidate) => candidate.depends_on?.includes(key))
        .map((candidate) => candidate.key)
    )
    setClearedEntityFields((current) => {
      const next = new Set(current)
      next.delete(key)
      for (const dependentKey of dependentKeys) {
        next.add(dependentKey)
      }
      return next
    })
    onEditsChange(
      Object.fromEntries(
        Object.entries({ ...decision.edits, [key]: nextValue }).filter(
          ([candidateKey]) => !dependentKeys.has(candidateKey)
        )
      )
    )
  }
  return (
    <div className="grid min-w-0 gap-3 sm:grid-flow-dense sm:grid-cols-2">
      {fields.map((field) => {
        const rawValue = args[field.key]
        const originalValue = editableValue(field.format, rawValue)
        const editable = field.editable && originalValue !== null
        const value = clearedEntityFields.has(field.key)
          ? field.format === "entity_list"
            ? []
            : null
          : originalValue === null
            ? ""
            : (decision.edits[field.key] ?? originalValue)
        const isEmptySecondary = field.secondary && isEmptyEditedValue(value)
        const isRevealed = revealedFields.has(field.key)

        if (decision.decision !== "pending") {
          const resolved = resolveApprovalField(field, lockedRecord[field.key])
          return resolved ? (
            <div className={fieldSpanClass(field.format)} key={field.key}>
              <ApprovalStaticField field={resolved} />
            </div>
          ) : null
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
        if (!editable) {
          const resolved = resolveApprovalField(field, rawValue)
          return resolved ? (
            <div className={fieldSpanClass(field.format)} key={field.key}>
              <ApprovalStaticField field={resolved} />
            </div>
          ) : null
        }
        if ((field.format === "entity" || field.format === "entity_list") && !conversationId) {
          return (
            <UnavailableEntityField
              field={field}
              key={field.key}
              onValidityChange={onEntityValidityChange}
            />
          )
        }

        const id = `${activityId}-${field.key}-edit`
        const focusRef = (node: HTMLElement | null) => {
          if (node && focusFieldKey.current === field.key) {
            focusFieldKey.current = null
            node.focus()
          }
        }
        return (
          <Field
            className={cn("gap-1", fieldSpanClass(field.format))}
            data-disabled={disabled}
            key={field.key}
          >
            <div className="flex items-center justify-between gap-2">
              <FieldLabel className={fieldLabelClass} htmlFor={id}>
                {field.label}
              </FieldLabel>
              {field.secondary && isRevealed ? (
                <Button
                  className="h-auto px-1 py-0 text-xs"
                  disabled={disabled}
                  onClick={() => {
                    onEditsChange(withoutEdit(decision.edits, field.key))
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
              ) : null}
            </div>
            {(field.format === "entity" || field.format === "entity_list") && conversationId ? (
              <EntityFieldInput
                conversationId={conversationId}
                dependentArgs={lockedRecord}
                disabled={disabled}
                field={field}
                id={id}
                onChange={(nextValue) => {
                  applyFieldEdit(field.key, nextValue)
                }}
                onValidityChange={onEntityValidityChange}
                toolName={toolName}
                value={value}
              />
            ) : field.options.length > 0 && typeof value === "string" ? (
              <Select<string>
                disabled={disabled}
                onValueChange={(nextValue) => {
                  if (nextValue !== null) {
                    applyFieldEdit(field.key, nextValue)
                  }
                }}
                value={value}
              >
                <SelectTrigger className={cn(fieldWellClass, "h-8")} id={id} ref={focusRef}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent align="start">
                  <SelectGroup>
                    {field.options.map((option) => (
                      <SelectItem
                        key={option}
                        label={titleCaseToken(option, option)}
                        value={option}
                      >
                        {titleCaseToken(option, option)}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            ) : field.format === "list" &&
              Array.isArray(value) &&
              value.every((item): item is string => typeof item === "string") ? (
              <ListFieldInput
                disabled={disabled}
                id={id}
                onChange={(nextValue) => {
                  applyFieldEdit(field.key, nextValue)
                }}
                {...(field.placeholder ? { placeholder: field.placeholder } : {})}
                value={value}
              />
            ) : field.format === "keyvalue" && isEditedKeyValue(value) ? (
              <KeyValueFieldInput
                disabled={disabled}
                id={id}
                lockedEntries={lockedKeyValueEntries(rawValue)}
                onChange={(nextValue) => {
                  applyFieldEdit(field.key, nextValue)
                }}
                value={value}
              />
            ) : field.format === "number" && typeof value === "number" ? (
              <Input
                className={fieldWellClass}
                defaultValue={value}
                disabled={disabled}
                id={id}
                inputMode="decimal"
                onChange={(event) => {
                  const raw = event.currentTarget.value
                  const nextValue = Number(raw)
                  if (!raw) {
                    onEditsChange(withoutEdit(decision.edits, field.key))
                  } else if (
                    Number.isFinite(nextValue) &&
                    (!Number.isInteger(rawValue) || Number.isInteger(nextValue))
                  ) {
                    applyFieldEdit(field.key, nextValue)
                  } else {
                    event.currentTarget.value = String(value)
                  }
                }}
                ref={focusRef}
                step={Number.isInteger(rawValue) ? 1 : "any"}
                type="number"
              />
            ) : typeof value === "string" &&
              (field.format === "multiline" || field.format === "markdown" || value.length > 80) ? (
              <Textarea
                className={cn(fieldWellClass, "min-h-16")}
                disabled={disabled}
                id={id}
                onChange={changeHandler(field.key, applyFieldEdit)}
                placeholder={field.placeholder || undefined}
                ref={focusRef}
                value={value}
              />
            ) : typeof value === "string" ? (
              <Input
                className={fieldWellClass}
                disabled={disabled}
                id={id}
                onChange={changeHandler(field.key, applyFieldEdit)}
                placeholder={field.placeholder || undefined}
                ref={focusRef}
                value={value}
              />
            ) : null}
          </Field>
        )
      })}
      {fallbackFields.length > 0 ? (
        <details className="group min-w-0 rounded-md border sm:col-span-2">
          <summary className="focus-visible:ring-ring flex cursor-pointer list-none items-center justify-between gap-3 rounded-md px-3 py-2 text-xs font-medium outline-none focus-visible:ring-2 focus-visible:ring-offset-2 [&::-webkit-details-marker]:hidden">
            <span>
              Other Options
              <span className="text-muted-foreground ml-1.5 font-normal">
                ({String(fallbackFields.length)})
              </span>
            </span>
            <ChevronDownIcon
              aria-hidden="true"
              className="text-muted-foreground size-3.5 transition-transform group-open:rotate-180"
            />
          </summary>
          <div className="grid min-w-0 gap-3 border-t p-3">
            {fallbackFields.map((field) => (
              <ApprovalStaticField field={field} key={field.key} />
            ))}
          </div>
        </details>
      ) : null}
    </div>
  )
}

function UnavailableEntityField({
  field,
  onValidityChange,
}: {
  field: ApprovalField
  onValidityChange: (key: string, valid: boolean) => void
}) {
  useEffect(() => {
    onValidityChange(field.key, false)
    return () => {
      onValidityChange(field.key, true)
    }
  }, [field.key, onValidityChange])

  return (
    <Field className={cn("gap-1", fieldSpanClass(field.format))} data-disabled>
      <FieldLabel className={fieldLabelClass}>{field.label}</FieldLabel>
      <div className={cn(fieldWellClass, "text-muted-foreground flex items-center")}>
        Target unavailable
      </div>
      <p className="text-destructive text-xs">
        This target cannot be verified outside its conversation.
      </p>
    </Field>
  )
}

function fieldSpanClass(format: ToolFieldFormat): string | undefined {
  return ["multiline", "markdown", "list", "keyvalue", "entity", "entity_list"].includes(format)
    ? "sm:col-span-2"
    : undefined
}

function editableValue(format: ToolFieldFormat, value: unknown): EditedValue | null {
  if (format === "text" || format === "multiline" || format === "markdown") {
    return typeof value === "string" ? value : null
  }
  if (format === "number") {
    return typeof value === "number" && Number.isFinite(value) ? value : null
  }
  if (format === "list") {
    return Array.isArray(value) && value.every((item) => typeof item === "string")
      ? [...value]
      : null
  }
  if (format === "keyvalue" && isRecord(value)) {
    return Object.fromEntries(
      Object.entries(value).filter((entry): entry is [string, string | number | boolean] =>
        isEditedScalar(entry[1])
      )
    )
  }
  if (format === "entity" && isRecord(value)) {
    return value
  }
  if (format === "entity_list" && Array.isArray(value) && value.every(isRecord)) {
    return value
  }
  return null
}

function resolveApprovalField(field: ApprovalField, value: unknown): ApprovalFallbackField | null {
  const resolved = resolveToolField(field, value)
  if (resolved === null || (!resolved.value.trim() && field.secondary)) {
    return null
  }
  return resolved
}

function changeHandler(key: string, applyFieldEdit: (key: string, value: EditedValue) => void) {
  return (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    applyFieldEdit(key, event.currentTarget.value)
  }
}

function isEmptyEditedValue(value: unknown): boolean {
  if (typeof value === "string") {
    return !value.trim()
  }
  if (Array.isArray(value)) {
    return value.length === 0
  }
  return value !== null && typeof value === "object" && Object.keys(value).length === 0
}

function isEditedScalar(value: unknown): value is string | number | boolean {
  return (
    typeof value === "string" ||
    typeof value === "boolean" ||
    (typeof value === "number" && Number.isFinite(value))
  )
}

function isEditedKeyValue(value: unknown): value is EditedKeyValue {
  return value !== null && typeof value === "object" && !Array.isArray(value)
}

function lockedKeyValueEntries(value: unknown): string[] {
  if (!isRecord(value)) {
    return []
  }
  return Object.entries(value).flatMap(([key, item]) => (isEditedScalar(item) ? [] : [key]))
}

function withoutEdit(edits: EditedValues, key: string): EditedValues {
  return Object.fromEntries(Object.entries(edits).filter(([editKey]) => editKey !== key))
}

function resolveLockedRecord(
  args: Record<string, unknown>,
  edits: EditedValues
): Record<string, unknown> {
  const resolved = { ...args }
  for (const [key, edit] of Object.entries(edits)) {
    const original = args[key]
    if (isEditedKeyValue(edit) && isRecord(original)) {
      const complexEntries = Object.entries(original).filter(([, value]) => !isEditedScalar(value))
      resolved[key] = { ...edit, ...Object.fromEntries(complexEntries) }
    } else {
      resolved[key] = edit
    }
  }
  return resolved
}
