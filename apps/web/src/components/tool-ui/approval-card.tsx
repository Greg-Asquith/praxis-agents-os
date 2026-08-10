// apps/web/src/components/tool-ui/approval-card.tsx

import { useCallback, useRef, useState, type ReactNode } from "react"
import { CheckIcon, WrenchIcon } from "lucide-react"

import { ApprovalRequestFields } from "@/components/tool-ui/approval-request-fields"
import { ApprovalStaticField } from "@/components/tool-ui/approval-static-field"
import type {
  ApprovalDecision,
  ApprovalFallbackField,
  ApprovalField,
  ToolApprovalDecisionControls,
} from "@/components/tool-ui/approval-types"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Field, FieldLabel } from "@/components/ui/field"
import { Textarea } from "@/components/ui/textarea"
import { pluralize } from "@/lib/format"
import { cn } from "@/lib/utils"

export type {
  ApprovalDecision,
  ApprovalFallbackField,
  ApprovalField,
  ToolApprovalDecisionControls,
} from "./approval-types"
export { ApprovalRequestFields } from "./approval-request-fields"

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
  toolName,
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
  toolName: string
}) {
  const [isDeclining, setIsDeclining] = useState(false)
  const [denialMessage, setDenialMessage] = useState("")
  const [invalidEntityFields, setInvalidEntityFields] = useState<Set<string>>(() => new Set())
  const disabled = controls.disabled ?? false
  const isDecided = controls.decision.decision !== "pending"
  const handleEntityValidityChange = useCallback((key: string, valid: boolean) => {
    setInvalidEntityFields((current) => {
      const next = new Set(current)
      if (valid) {
        next.delete(key)
      } else {
        next.add(key)
      }
      return next
    })
  }, [])

  return (
    <ToolApprovalCard
      decision={controls.decision.decision}
      footer={
        <ApprovalFooter
          approveLabel={approveLabel}
          controls={controls}
          disabled={disabled || invalidEntityFields.size > 0}
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
          onEntityValidityChange={handleEntityValidityChange}
          toolName={toolName}
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
      <div className="border-border flex min-w-0 flex-col gap-2 border-t px-4 py-3">{footer}</div>
    </section>
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
