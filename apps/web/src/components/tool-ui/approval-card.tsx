// apps/web/src/components/tool-ui/approval-card.tsx

import { useCallback, useRef, useState, type ChangeEvent, type ReactNode } from "react"
import { CheckIcon, WrenchIcon } from "lucide-react"

import {
  resolveToolField,
  type ResolvedToolField,
  type ToolFieldFormat,
} from "@/components/tool-ui/field-resolution"
import { fieldLabelClass, fieldWellClass } from "@/components/tool-ui/field-styles"
import { ToolFieldValue } from "@/components/tool-ui/field-value"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
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
import { pluralize, titleCaseToken } from "@/lib/format"
import { isRecord } from "@/lib/guards"
import { cn } from "@/lib/utils"

export type ApprovalDecision =
  | { decision: "pending"; edits: Record<string, string>; message: "" }
  | { decision: "approved"; edits: Record<string, string>; message: "" }
  | { decision: "denied"; edits: Record<string, string>; message: string }

export type ToolApprovalDecisionControls = {
  decision: ApprovalDecision
  disabled?: boolean
  error: string | null
  onDecisionChange: (decision: ApprovalDecision) => void
  onRetry: () => void
  pendingCount: number
  submitting: boolean
}

export type ApprovalField = {
  editable: boolean
  format: ToolFieldFormat
  key: string
  label: string
  options: string[]
  placeholder: string
  secondary: boolean
}

export type ApprovalFallbackField = ResolvedToolField

const NO_FIELDS: ApprovalField[] = []
const NO_FALLBACK_FIELDS: ApprovalFallbackField[] = []

export function ToolApprovalDecisionCard({
  activityId,
  approveLabel = "Approve",
  args,
  children,
  controls,
  fallbackFields = NO_FALLBACK_FIELDS,
  fields = NO_FIELDS,
  icon,
  label,
  prompt,
  title = label,
}: {
  activityId: string
  approveLabel?: string
  args: unknown
  children?: ReactNode
  controls: ToolApprovalDecisionControls
  fallbackFields?: ApprovalFallbackField[]
  fields?: ApprovalField[]
  icon?: ReactNode
  label: string
  prompt?: string
  title?: string
}) {
  const [isDeclining, setIsDeclining] = useState(false)
  const [denialMessage, setDenialMessage] = useState("")
  const disabled = controls.disabled ?? false
  const isDecided = controls.decision.decision !== "pending"

  return (
    <ToolApprovalCard
      decision={controls.decision.decision}
      footer={
        <ApprovalFooter
          approveLabel={approveLabel}
          controls={controls}
          disabled={disabled}
          isDeclining={isDeclining}
          label={label}
          onApprove={() => {
            controls.onDecisionChange({
              decision: "approved",
              edits:
                controls.decision.decision === "pending" ||
                controls.decision.decision === "approved"
                  ? controls.decision.edits
                  : {},
              message: "",
            })
          }}
          onBack={() => {
            setIsDeclining(false)
          }}
          onDecline={() => {
            setIsDeclining(true)
          }}
          onDeclineConfirm={() => {
            controls.onDecisionChange({ decision: "denied", edits: {}, message: denialMessage })
          }}
        />
      }
      icon={icon}
      {...(prompt ? { prompt } : {})}
      title={title}
    >
      {isDeclining && !isDecided ? (
        <ApprovalDenialMessageField
          disabled={disabled}
          id={`${activityId}-message`}
          onChange={setDenialMessage}
          value={denialMessage}
        />
      ) : (
        <ApprovalRequestFields
          activityId={activityId}
          args={args}
          decision={controls.decision}
          disabled={disabled || isDecided}
          fallbackFields={fallbackFields}
          fields={fields}
          onEditsChange={(edits) => {
            controls.onDecisionChange({ decision: "pending", edits, message: "" })
          }}
        />
      )}
      {controls.decision.decision === "denied" && controls.decision.message ? (
        <ApprovalStaticField
          field={{
            key: "denial-message",
            label: "Message to Agent",
            value: controls.decision.message,
            format: "multiline",
          }}
        />
      ) : null}
      {children}
    </ToolApprovalCard>
  )
}

export function ToolApprovalCard({
  children,
  decision,
  footer,
  icon,
  prompt,
  title,
}: {
  children: ReactNode
  decision: ApprovalDecision["decision"]
  footer: ReactNode
  icon?: ReactNode
  prompt?: string
  title: string
}) {
  const awaitingDecision = decision === "pending"

  return (
    <section
      aria-label={`Approval request: ${title}`}
      className={cn(
        "bg-card w-full min-w-0 overflow-hidden rounded-lg border shadow-xs",
        awaitingDecision && "border-warning/40"
      )}
    >
      <div className="flex min-w-0 items-start gap-3 px-4 pt-4">
        <div className="bg-muted text-muted-foreground mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg">
          {icon ?? <WrenchIcon className="size-4" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <h3 className="text-foreground text-sm font-medium">{title}</h3>
            {awaitingDecision ? (
              <Badge variant="warning">Requires Approval</Badge>
            ) : decision === "approved" ? (
              <span className="text-success inline-flex items-center gap-1 text-xs font-medium">
                Approved <CheckIcon className="size-3.5" />
              </span>
            ) : (
              <span className="text-muted-foreground text-xs font-medium">Declined</span>
            )}
          </div>
          {awaitingDecision && prompt ? (
            <p className="text-muted-foreground mt-1 text-sm leading-relaxed">{prompt}</p>
          ) : null}
        </div>
      </div>
      <div className="flex min-w-0 flex-col gap-3 px-4 py-4">{children}</div>
      <div className="border-border/60 flex min-w-0 flex-col gap-2 border-t px-4 py-3">
        {footer}
      </div>
    </section>
  )
}

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
  decision: ApprovalDecision
  disabled: boolean
  fallbackFields: ApprovalFallbackField[]
  fields: ApprovalField[]
  onEditsChange: (edits: Record<string, string>) => void
}) {
  const [revealedFields, setRevealedFields] = useState<Set<string>>(() => new Set())
  const focusFieldKey = useRef<string | null>(null)

  if (fields.length === 0 || !isRecord(args)) {
    return fallbackFields.length > 0 ? (
      <div className="grid min-w-0 gap-3">
        {fallbackFields.map((field) => (
          <ApprovalStaticField field={field} key={field.key} />
        ))}
      </div>
    ) : null
  }

  const lockedRecord = { ...args, ...decision.edits }
  return (
    <div className="grid min-w-0 gap-3">
      {fields.map((field) => {
        const rawValue = args[field.key]
        const originalValue = editableValue(rawValue)
        const editable = field.editable && originalValue !== null
        const value = originalValue === null ? "" : (decision.edits[field.key] ?? originalValue)
        const isEmptySecondary = field.secondary && !value.trim()
        const isRevealed = revealedFields.has(field.key)

        if (decision.decision !== "pending") {
          const resolved = resolveApprovalField(field, lockedRecord[field.key])
          return resolved ? <ApprovalStaticField field={resolved} key={field.key} /> : null
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
          return resolved ? <ApprovalStaticField field={resolved} key={field.key} /> : null
        }

        const id = `${activityId}-${field.key}-edit`
        const focusRef = (node: HTMLElement | null) => {
          if (node && focusFieldKey.current === field.key) {
            focusFieldKey.current = null
            node.focus()
          }
        }
        return (
          <Field className="gap-1" data-disabled={disabled} key={field.key}>
            <div className="flex items-center justify-between gap-2">
              <FieldLabel className={fieldLabelClass} htmlFor={id}>
                {field.label}
              </FieldLabel>
              {field.secondary && isRevealed ? (
                <Button
                  className="h-auto px-1 py-0 text-xs"
                  disabled={disabled}
                  onClick={() => {
                    onEditsChange(
                      Object.fromEntries(
                        Object.entries(decision.edits).filter(([key]) => key !== field.key)
                      )
                    )
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
            ) : field.format === "multiline" || value.length > 80 ? (
              <Textarea
                className={cn(fieldWellClass, "min-h-16")}
                disabled={disabled}
                id={id}
                onChange={changeHandler(field.key, decision.edits, onEditsChange)}
                placeholder={field.placeholder || undefined}
                ref={focusRef}
                value={value}
              />
            ) : (
              <Input
                className={fieldWellClass}
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
      })}
    </div>
  )
}

function ApprovalFooter({
  approveLabel,
  controls,
  disabled,
  isDeclining,
  label,
  onApprove,
  onBack,
  onDecline,
  onDeclineConfirm,
}: {
  approveLabel: string
  controls: ToolApprovalDecisionControls
  disabled: boolean
  isDeclining: boolean
  label: string
  onApprove: () => void
  onBack: () => void
  onDecline: () => void
  onDeclineConfirm: () => void
}) {
  const decision = controls.decision.decision
  return (
    <>
      {controls.error ? (
        <Alert variant="destructive">
          <AlertTitle>Couldn’t continue</AlertTitle>
          <AlertDescription>{controls.error}</AlertDescription>
        </Alert>
      ) : null}
      {decision !== "pending" && controls.pendingCount > 0 ? (
        <p className="text-muted-foreground text-xs">
          Waiting for your decision on {String(controls.pendingCount)} more{" "}
          {pluralize(controls.pendingCount, "request")}.
        </p>
      ) : null}
      <div
        aria-busy={controls.submitting || undefined}
        aria-label={`Decision for ${label}`}
        className="flex min-w-0 items-center justify-end gap-1"
        role="group"
      >
        {controls.error ? (
          <Button disabled={disabled} onClick={controls.onRetry} size="sm" type="button">
            Try Again
          </Button>
        ) : decision === "pending" && isDeclining ? (
          <>
            <Button disabled={disabled} onClick={onBack} size="sm" type="button" variant="ghost">
              Back
            </Button>
            <Button
              disabled={disabled}
              onClick={onDeclineConfirm}
              size="sm"
              type="button"
              variant="destructive"
            >
              Decline Request
            </Button>
          </>
        ) : decision === "pending" ? (
          <>
            <Button disabled={disabled} onClick={onDecline} size="sm" type="button" variant="ghost">
              Decline
            </Button>
            <Button disabled={disabled} onClick={onApprove} size="sm" type="button">
              {approveLabel}
            </Button>
          </>
        ) : controls.submitting ? (
          <Button disabled size="sm" type="button">
            {decision === "approved" ? "Approving…" : "Declining…"}
          </Button>
        ) : null}
      </div>
    </>
  )
}

function ApprovalDenialMessageField({
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
        placeholder="For example: use a different recipient"
        ref={focusOnMount}
        value={value}
      />
    </Field>
  )
}

function ApprovalStaticField({ field }: { field: ApprovalFallbackField }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <p className={fieldLabelClass}>{field.label}</p>
      <div
        className={cn(
          fieldWellClass,
          "border-input bg-muted/40 wrap-break-word whitespace-pre-wrap"
        )}
      >
        <ToolFieldValue field={field} />
      </div>
    </div>
  )
}

function editableValue(value: unknown): string | null {
  return typeof value === "string" ? value : null
}

function resolveApprovalField(field: ApprovalField, value: unknown): ApprovalFallbackField | null {
  const resolved = resolveToolField(field, value)
  if (resolved === null || (!resolved.value.trim() && field.secondary)) {
    return null
  }
  return resolved
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
