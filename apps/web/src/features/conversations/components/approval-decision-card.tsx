// apps/web/src/features/conversations/components/approval-decision-card.tsx

import { CheckIcon, XIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { runtimeToolLabel } from "@/features/agents/runtime-tools"
import {
  approveDecision,
  denyDecision,
  type LocalApprovalDecision,
} from "@/features/conversations/approval-decisions"
import {
  ApprovalDenialMessageField,
  ApprovalOverrideInputField,
} from "@/features/conversations/components/approval-decision-fields"
import { ApprovalRequestedInput } from "@/features/conversations/components/approval-requested-input"
import { supportIdentifier } from "@/features/conversations/format"
import type { PendingToolApproval } from "@/features/conversations/types"
import { cn } from "@/lib/utils"

export function ApprovalDecisionCard({
  approval,
  decision,
  onDecisionChange,
}: {
  approval: PendingToolApproval
  decision: LocalApprovalDecision
  onDecisionChange: (decision: LocalApprovalDecision) => void
}) {
  const toolLabel = runtimeToolLabel(approval.name)
  const supportToolName = supportIdentifier(approval.name) ?? approval.name
  const supportToolCallId = supportIdentifier(approval.tool_call_id) ?? "unknown"

  return (
    <section
      className={cn(
        "grid gap-4 rounded-lg border p-3",
        decision.decision === "pending" ? "border-primary/30 bg-muted/20" : "bg-card"
      )}
    >
      <div className="flex flex-col justify-between gap-3 md:flex-row md:items-start">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-medium">Review tool request</p>
            <DecisionBadge decision={decision.decision} />
          </div>
          <p className="text-sm" title={toolLabel ? `Tool: ${approval.name}` : undefined}>
            {toolLabel ?? "Tool request"}
          </p>
          <details className="text-muted-foreground text-xs">
            <summary className="hover:text-foreground cursor-pointer">Support details</summary>
            <dl className="mt-1 grid gap-1 sm:grid-cols-2">
              <SupportDetail label="Tool" title={approval.name} value={supportToolName} />
              <SupportDetail label="Call" title={approval.tool_call_id} value={supportToolCallId} />
            </dl>
          </details>
        </div>
        <ApprovalDecisionButtons
          decision={decision.decision}
          label={toolLabel ?? "tool request"}
          onApprove={() => {
            onDecisionChange(approveDecision(decision))
          }}
          onDeny={() => {
            onDecisionChange(denyDecision(decision))
          }}
        />
      </div>

      <ApprovalRequestedInput value={approval.args} />

      {decision.decision === "approved" ? (
        <ApprovalOverrideInputField
          id={`${approval.tool_call_id}-override`}
          onChange={(overrideArgs) => {
            onDecisionChange({
              decision: "approved",
              message: "",
              overrideArgs,
            })
          }}
          value={decision.overrideArgs}
        />
      ) : null}

      {decision.decision === "denied" ? (
        <ApprovalDenialMessageField
          id={`${approval.tool_call_id}-message`}
          onChange={(message) => {
            onDecisionChange({
              decision: "denied",
              message,
              overrideArgs: "",
            })
          }}
          value={decision.message}
        />
      ) : null}

      {decision.decision === "pending" ? (
        <p className="text-muted-foreground rounded-md border border-dashed p-3 text-sm">
          Choose approve or deny for this request.
        </p>
      ) : null}
    </section>
  )
}

function ApprovalDecisionButtons({
  decision,
  label,
  onApprove,
  onDeny,
}: {
  decision: LocalApprovalDecision["decision"]
  label: string
  onApprove: () => void
  onDeny: () => void
}) {
  return (
    <div
      aria-label={`Decision for ${label}`}
      className="grid w-full grid-cols-2 gap-2 md:w-56"
      role="group"
    >
      <Button
        aria-pressed={decision === "approved"}
        onClick={onApprove}
        size="sm"
        type="button"
        variant={decision === "approved" ? "default" : "outline"}
      >
        <CheckIcon data-icon="inline-start" />
        Approve
      </Button>
      <Button
        aria-pressed={decision === "denied"}
        onClick={onDeny}
        size="sm"
        type="button"
        variant={decision === "denied" ? "destructive" : "outline"}
      >
        <XIcon data-icon="inline-start" />
        Deny
      </Button>
    </div>
  )
}

function DecisionBadge({ decision }: { decision: LocalApprovalDecision["decision"] }) {
  if (decision === "approved") {
    return <Badge variant="outline">Approved</Badge>
  }

  if (decision === "denied") {
    return <Badge variant="destructive">Denied</Badge>
  }

  return <Badge variant="secondary">Needs decision</Badge>
}

function SupportDetail({ label, title, value }: { label: string; title: string; value: string }) {
  return (
    <div className="flex min-w-0 gap-1">
      <dt>{label}</dt>
      <dd className="truncate font-mono" title={title}>
        {value}
      </dd>
    </div>
  )
}
