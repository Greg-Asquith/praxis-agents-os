// apps/web/src/features/conversations/components/tool-call-row.tsx

import {
  BotIcon,
  CheckCircle2Icon,
  ChevronRightIcon,
  CircleDashedIcon,
  ExternalLinkIcon,
  ShieldAlertIcon,
  TriangleAlertIcon,
  WrenchIcon,
} from "lucide-react"
import { Link } from "@tanstack/react-router"

import { buttonVariants } from "@/components/ui/button"
import { runtimeToolLabel } from "@/features/agents/runtime-tools"
import {
  approveDecision,
  denyDecision,
  type LocalApprovalDecision,
} from "@/features/conversations/approval-decisions"
import { ApprovalDecisionButtons } from "@/features/conversations/components/approval-decision-buttons"
import {
  ApprovalDenialMessageField,
  ApprovalOverrideInputField,
} from "@/features/conversations/components/approval-decision-fields"
import { supportIdentifier } from "@/features/conversations/format"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { safeJsonPreview } from "@/features/conversations/message-parts"
import { cn } from "@/lib/utils"

type ToolApprovalDecisionControls = {
  decision: LocalApprovalDecision
  disabled?: boolean
  onDecisionChange: (decision: LocalApprovalDecision) => void
}

type ToolCallRowProps = {
  approvalDecision?: ToolApprovalDecisionControls
  activity: ToolActivity
  compact?: boolean
  defaultOpen?: boolean
}

export function ToolCallRow({
  activity,
  approvalDecision,
  compact = false,
  defaultOpen = false,
}: ToolCallRowProps) {
  if (activity.delegate) {
    return (
      <DelegationToolRow
        activity={activity}
        {...(approvalDecision ? { approvalDecision } : {})}
        compact={compact}
        defaultOpen={defaultOpen}
      />
    )
  }

  const toolLabel = runtimeToolLabel(activity.name)
  const title = toolLabel ?? "Tool call"
  const supportLabel = toolLabel ? null : supportIdentifier(activity.name)
  const hasArgs = activity.args !== undefined && activity.args !== null
  const hasResult = activity.result !== undefined && activity.result !== null
  const decisionLabel = decisionForActivity(activity)
  const expandable =
    hasArgs || hasResult || decisionLabel !== null || approvalDecision !== undefined
  const textSize = compact ? "text-xs" : "text-sm"

  const header = (
    <>
      <ChevronRightIcon
        className={cn(
          "text-muted-foreground size-3.5 shrink-0 transition-transform group-open/tool:rotate-90",
          !expandable && "invisible"
        )}
      />
      <ToolActivityIcon activity={activity} />
      <span className="min-w-0 truncate">
        <span className="text-foreground font-medium">
          {verbForActivity(activity)} {title}
        </span>
        {supportLabel && (
          <span className="text-muted-foreground ml-1.5 font-mono text-xs">{supportLabel}</span>
        )}
      </span>
      <StatusSuffix activity={activity} />
    </>
  )

  if (!expandable) {
    return (
      <div className={cn("text-muted-foreground flex min-w-0 items-center gap-2", textSize)}>
        {header}
      </div>
    )
  }

  return (
    <details className="group/tool min-w-0" open={defaultOpen ? true : undefined}>
      <summary
        className={cn(
          "text-muted-foreground hover:text-foreground flex min-w-0 cursor-pointer list-none items-center gap-2",
          textSize
        )}
      >
        {header}
      </summary>
      <div className="mt-2 ml-5 flex flex-col gap-3">
        {hasArgs && <JsonBlock label="Input" value={activity.args} />}
        {approvalDecision ? (
          <ApprovalDecisionBlock activity={activity} controls={approvalDecision} label={title} />
        ) : decisionLabel ? (
          <TextBlock label="Decision" value={decisionLabel} />
        ) : null}
        {hasResult && <JsonBlock label="Output" value={activity.result} />}
      </div>
    </details>
  )
}

function DelegationToolRow({
  activity,
  approvalDecision,
  compact,
  defaultOpen,
}: {
  activity: ToolActivity
  approvalDecision?: ToolApprovalDecisionControls
  compact: boolean
  defaultOpen: boolean
}) {
  const delegate = activity.delegate
  if (!delegate) {
    return null
  }

  const textSize = compact ? "text-xs" : "text-sm"
  const targetLabel = delegate.agentName ?? "Delegate agent"
  const supportLabel = supportIdentifier(delegate.agentId)
  const expandable =
    Boolean(approvalDecision) ||
    (activity.args !== undefined && activity.args !== null) ||
    Boolean(delegate.taskPreview) ||
    Boolean(delegate.output) ||
    Boolean(delegate.error) ||
    Boolean(delegate.conversationId) ||
    Boolean(delegate.runId) ||
    delegate.pendingApprovalCount > 0
  const shouldOpen =
    defaultOpen || delegate.status === "awaiting_approval" || delegate.status === "failed"
  const header = (
    <>
      <ChevronRightIcon
        className={cn(
          "text-muted-foreground size-3.5 shrink-0 transition-transform group-open/tool:rotate-90",
          !expandable && "invisible"
        )}
      />
      <DelegationStatusIcon status={delegate.status} />
      <span className="min-w-0 truncate">
        <span className="text-foreground font-medium">
          {delegationVerb(delegate.status)} {targetLabel}
        </span>
        {supportLabel && (
          <span className="text-muted-foreground ml-1.5 font-mono text-xs">{supportLabel}</span>
        )}
      </span>
      <DelegationStatusSuffix status={delegate.status} />
    </>
  )

  if (!expandable) {
    return (
      <div className={cn("text-muted-foreground flex min-w-0 items-center gap-2", textSize)}>
        {header}
      </div>
    )
  }

  return (
    <details className="group/tool min-w-0" open={shouldOpen ? true : undefined}>
      <summary
        className={cn(
          "text-muted-foreground hover:text-foreground flex min-w-0 cursor-pointer list-none items-center gap-2",
          textSize
        )}
      >
        {header}
      </summary>
      <div className="mt-2 ml-5 flex min-w-0 flex-col gap-3">
        {delegate.taskPreview ? <TextBlock label="Task" value={delegate.taskPreview} /> : null}
        {approvalDecision ? (
          <TextBlock label="Tool" value={runtimeToolLabel(activity.name) ?? activity.name} />
        ) : null}
        {approvalDecision && activity.args !== undefined && activity.args !== null ? (
          <JsonBlock label="Input" value={activity.args} />
        ) : null}
        {approvalDecision ? (
          <ApprovalDecisionBlock
            activity={activity}
            controls={approvalDecision}
            label={runtimeToolLabel(activity.name) ?? activity.name}
          />
        ) : null}
        {delegate.output ? (
          <TextBlock
            label="Result"
            value={delegate.truncated ? `${delegate.output}\n...` : delegate.output}
          />
        ) : null}
        {delegate.error ? <TextBlock label="Error" value={delegate.error} /> : null}
        {delegate.pendingApprovalCount > 0 ? (
          <TextBlock
            label="Approval"
            value={`${String(delegate.pendingApprovalCount)} pending request${
              delegate.pendingApprovalCount === 1 ? "" : "s"
            }`}
          />
        ) : null}
        {(delegate.conversationId !== null || delegate.runId !== null) && (
          <DelegationMetadata conversationId={delegate.conversationId} runId={delegate.runId} />
        )}
      </div>
    </details>
  )
}

function DelegationMetadata({
  conversationId,
  runId,
}: {
  conversationId: string | null
  runId: string | null
}) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2">
      {conversationId ? (
        <Link
          className={cn(buttonVariants({ variant: "outline", size: "sm" }), "max-w-full")}
          params={{ conversationId }}
          to="/conversations/$conversationId"
        >
          <ExternalLinkIcon data-icon="inline-start" />
          Open transcript
        </Link>
      ) : null}
      {runId ? (
        <span className="text-muted-foreground bg-muted/50 rounded-md px-2 py-1 font-mono text-xs">
          run {supportIdentifier(runId)}
        </span>
      ) : null}
      {conversationId ? (
        <span className="text-muted-foreground bg-muted/50 rounded-md px-2 py-1 font-mono text-xs">
          convo {supportIdentifier(conversationId)}
        </span>
      ) : null}
    </div>
  )
}

function ApprovalDecisionBlock({
  activity,
  controls,
  label,
}: {
  activity: ToolActivity
  controls: ToolApprovalDecisionControls
  label: string
}) {
  return (
    <div className="min-w-0">
      <p className="text-muted-foreground mb-2 text-xs font-medium">Decision</p>
      <div className="flex min-w-0 flex-col gap-3">
        <ApprovalDecisionButtons
          decision={controls.decision.decision}
          disabled={controls.disabled ?? false}
          label={label}
          onApprove={() => {
            controls.onDecisionChange(approveDecision(controls.decision))
          }}
          onDeny={() => {
            controls.onDecisionChange(denyDecision(controls.decision))
          }}
        />
        {controls.decision.decision === "approved" ? (
          <ApprovalOverrideInputField
            id={`${activity.id}-override`}
            onChange={(overrideArgs) => {
              controls.onDecisionChange({
                decision: "approved",
                message: "",
                overrideArgs,
              })
            }}
            value={controls.decision.overrideArgs}
          />
        ) : null}
        {controls.decision.decision === "denied" ? (
          <ApprovalDenialMessageField
            id={`${activity.id}-message`}
            onChange={(message) => {
              controls.onDecisionChange({
                decision: "denied",
                message,
                overrideArgs: "",
              })
            }}
            value={controls.decision.message}
          />
        ) : null}
        {controls.decision.decision === "pending" ? (
          <p className="text-muted-foreground bg-muted/30 rounded-md px-3 py-2 text-xs">
            Choose approve or deny for this request.
          </p>
        ) : null}
      </div>
    </div>
  )
}

function TextBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="text-muted-foreground mb-1 text-xs font-medium">{label}</p>
      <p className="bg-muted/50 rounded-md p-2 text-xs leading-relaxed">{value}</p>
    </div>
  )
}

function JsonBlock({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="min-w-0">
      <p className="text-muted-foreground mb-1 text-xs font-medium">{label}</p>
      <pre className="bg-muted/50 max-h-64 overflow-auto rounded-md p-2 text-xs leading-relaxed whitespace-pre-wrap">
        {safeJsonPreview(value)}
      </pre>
    </div>
  )
}

function StatusSuffix({ activity }: { activity: ToolActivity }) {
  const suffix = statusSuffix(activity)
  if (!suffix) {
    return null
  }

  return (
    <span
      className={cn(
        "shrink-0 text-xs",
        activity.status === "failed" || activity.status === "denied"
          ? "text-destructive"
          : "text-muted-foreground"
      )}
    >
      {suffix}
    </span>
  )
}

function ToolActivityIcon({ activity }: { activity: ToolActivity }) {
  if (activity.status === "awaiting_approval") {
    return <ShieldAlertIcon className="text-muted-foreground size-3.5 shrink-0" />
  }
  if (activity.status === "failed" || activity.status === "denied") {
    return <TriangleAlertIcon className="text-destructive size-3.5 shrink-0" />
  }
  if (activity.status === "completed") {
    return <CheckCircle2Icon className="text-muted-foreground size-3.5 shrink-0" />
  }
  if (activity.status === "running") {
    return <CircleDashedIcon className="text-muted-foreground size-3.5 shrink-0 animate-spin" />
  }
  return <WrenchIcon className="text-muted-foreground size-3.5 shrink-0" />
}

function DelegationStatusIcon({
  status,
}: {
  status: NonNullable<ToolActivity["delegate"]>["status"]
}) {
  if (status === "awaiting_approval") {
    return <ShieldAlertIcon className="text-muted-foreground size-3.5 shrink-0" />
  }
  if (status === "failed") {
    return <TriangleAlertIcon className="text-destructive size-3.5 shrink-0" />
  }
  if (status === "completed") {
    return <CheckCircle2Icon className="text-muted-foreground size-3.5 shrink-0" />
  }
  if (status === "running") {
    return <CircleDashedIcon className="text-muted-foreground size-3.5 shrink-0 animate-spin" />
  }
  return <BotIcon className="text-muted-foreground size-3.5 shrink-0" />
}

function verbForActivity(activity: ToolActivity) {
  if (activity.status === "running") {
    return "Running"
  }
  if (activity.status === "awaiting_approval") {
    return "Requested"
  }
  if (activity.status === "denied") {
    return "Denied"
  }
  return "Ran"
}

function statusSuffix(activity: ToolActivity) {
  if (activity.status === "awaiting_approval") {
    return "· waiting"
  }
  if (activity.status === "failed") {
    return "· failed"
  }
  if (activity.status === "denied") {
    return "· denied"
  }
  return null
}

function DelegationStatusSuffix({
  status,
}: {
  status: NonNullable<ToolActivity["delegate"]>["status"]
}) {
  const suffix = delegationStatusSuffix(status)
  if (!suffix) {
    return null
  }

  return (
    <span
      className={cn(
        "shrink-0 text-xs",
        status === "failed" ? "text-destructive" : "text-muted-foreground"
      )}
    >
      {suffix}
    </span>
  )
}

function delegationVerb(status: NonNullable<ToolActivity["delegate"]>["status"]) {
  if (status === "running") {
    return "Delegating to"
  }
  if (status === "failed") {
    return "Delegation failed for"
  }
  return "Delegated to"
}

function delegationStatusSuffix(status: NonNullable<ToolActivity["delegate"]>["status"]) {
  if (status === "awaiting_approval") {
    return "· waiting"
  }
  if (status === "failed") {
    return "· failed"
  }
  if (status === "unknown") {
    return "· unknown"
  }
  return null
}

function decisionForActivity(activity: ToolActivity) {
  if (activity.decision === "approved") {
    return "Approved"
  }
  if (activity.decision === "denied") {
    return "Denied"
  }
  if (activity.status === "awaiting_approval") {
    return "Waiting for approval"
  }
  if (activity.status === "denied") {
    return "Denied"
  }
  return null
}
