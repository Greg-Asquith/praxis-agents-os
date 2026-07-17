// apps/web/src/features/conversations/components/approval-decision-block.tsx

import { useState, type ReactNode } from "react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  approveDecision,
  type LocalApprovalDecision,
} from "@/features/conversations/approval-decisions"
import {
  ApprovalDenialMessageField,
  ApprovalRequestFields,
} from "@/features/conversations/components/approval-decision-fields"
import { ToolApprovalCard } from "@/features/conversations/components/tool-approval-card"
import { ToolField } from "@/features/conversations/components/tool-field"
import type { ToolActivity } from "@/features/conversations/message-parts"
import type { ResolvedToolField } from "@/features/conversations/tool-ui"
import type { ToolUiField } from "@/features/tools/types"
import { pluralize } from "@/lib/format"

const NO_DECLARED_FIELDS: ToolUiField[] = []
const NO_FALLBACK_FIELDS: ResolvedToolField[] = []

export type ToolApprovalDecisionControls = {
  decision: LocalApprovalDecision
  disabled?: boolean
  error: string | null
  onDecisionChange: (decision: LocalApprovalDecision) => void
  onRetry: () => void
  pendingCount: number
  submitting: boolean
}

export function ApprovalDecisionBlock({
  activity,
  approveLabel = "Approve",
  children,
  controls,
  fields = NO_DECLARED_FIELDS,
  fallbackFields = NO_FALLBACK_FIELDS,
  iconToken = null,
  label,
  prompt,
  title = label,
}: {
  activity: ToolActivity
  approveLabel?: string
  children?: ReactNode
  controls: ToolApprovalDecisionControls
  fields?: ToolUiField[]
  fallbackFields?: ResolvedToolField[]
  iconToken?: string | null
  label: string
  prompt?: string
  title?: string
}) {
  const [isDeclining, setIsDeclining] = useState(false)
  const [denialMessage, setDenialMessage] = useState("")
  const disabled = controls.disabled ?? false
  const isDecided = controls.decision.decision !== "pending"

  function updateEdits(edits: Record<string, string>) {
    controls.onDecisionChange({ decision: "pending", edits, message: "" })
  }

  const fieldsContent = (
    <ApprovalRequestFields
      activityId={activity.id}
      args={activity.args}
      decision={controls.decision}
      disabled={disabled || isDecided}
      fallbackFields={fallbackFields}
      fields={fields}
      onEditsChange={updateEdits}
    />
  )

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
          onBack={() => {
            setIsDeclining(false)
          }}
          onDecline={() => {
            setIsDeclining(true)
          }}
          onDeclineConfirm={() => {
            controls.onDecisionChange({
              decision: "denied",
              edits: {},
              message: denialMessage,
            })
          }}
          onApprove={() => {
            controls.onDecisionChange(approveDecision(controls.decision))
          }}
        />
      }
      iconToken={iconToken}
      {...(prompt ? { prompt } : {})}
      title={title}
    >
      {isDeclining && !isDecided ? (
        <ApprovalDenialMessageField
          disabled={disabled}
          id={`${activity.id}-message`}
          onChange={setDenialMessage}
          value={denialMessage}
        />
      ) : (
        fieldsContent
      )}
      {controls.decision.decision === "denied" && controls.decision.message ? (
        <ToolField
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
  const remaining = controls.pendingCount

  return (
    <>
      {controls.error ? (
        <Alert variant="destructive">
          <AlertTitle>Couldn’t continue</AlertTitle>
          <AlertDescription>{controls.error}</AlertDescription>
        </Alert>
      ) : null}
      {decision !== "pending" && remaining > 0 ? (
        <p className="text-muted-foreground text-xs">
          Waiting for your decision on {String(remaining)} more {pluralize(remaining, "request")}.
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
