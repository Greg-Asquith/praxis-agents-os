// apps/web/src/features/conversations/components/delegation-tool-row.tsx

import { Link } from "@tanstack/react-router"
import { ExternalLinkIcon } from "lucide-react"

import { buttonVariants } from "@/components/ui/button"
import { runtimeToolLabel } from "@/features/agents/runtime-tools"
import {
  ApprovalDecisionBlock,
  type ToolApprovalDecisionControls,
} from "@/features/conversations/components/approval-decision-block"
import { JsonBlock, TextBlock } from "@/features/conversations/components/tool-call-content-blocks"
import {
  ToolActivityRowHeader,
  ToolActivityRowShell,
} from "@/features/conversations/components/tool-activity-row-shell"
import {
  ActivityStatusIcon,
  ActivityStatusSuffix,
} from "@/features/conversations/components/tool-activity-status"
import {
  delegationActivityVerb,
  delegationStatusSuffix,
} from "@/features/conversations/components/tool-activity-status-values"
import { supportIdentifier } from "@/features/conversations/format"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { pluralize } from "@/lib/format"
import { cn } from "@/lib/utils"

type DelegationToolRowProps = {
  activity: ToolActivity
  approvalDecision?: ToolApprovalDecisionControls
  compact: boolean
  defaultOpen: boolean
}

export function DelegationToolRow({
  activity,
  approvalDecision,
  compact,
  defaultOpen,
}: DelegationToolRowProps) {
  const delegate = activity.delegate
  if (!delegate) {
    return null
  }

  const targetLabel = delegate.agentName ?? "Delegate agent"
  const supportLabel = supportIdentifier(delegate.agentId)
  const toolLabel = runtimeToolLabel(activity.name) ?? activity.name
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
    <ToolActivityRowHeader
      expandable={expandable}
      icon={<ActivityStatusIcon fallbackIcon="delegation" status={delegate.status} />}
      label={
        <>
          {delegationActivityVerb(delegate.status)} {targetLabel}
        </>
      }
      suffix={
        <ActivityStatusSuffix
          status={delegate.status}
          suffix={delegationStatusSuffix(delegate.status)}
        />
      }
      supportLabel={supportLabel}
    />
  )

  return (
    <ToolActivityRowShell
      compact={compact}
      defaultOpen={shouldOpen}
      expandable={expandable}
      header={header}
    >
      {delegate.taskPreview ? <TextBlock label="Task" value={delegate.taskPreview} /> : null}
      {approvalDecision ? <TextBlock label="Tool" value={toolLabel} /> : null}
      {approvalDecision && activity.args !== undefined && activity.args !== null ? (
        <JsonBlock label="Input" value={activity.args} />
      ) : null}
      {approvalDecision ? (
        <ApprovalDecisionBlock activity={activity} controls={approvalDecision} label={toolLabel} />
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
          value={`${String(delegate.pendingApprovalCount)} pending ${pluralize(
            delegate.pendingApprovalCount,
            "request"
          )}`}
        />
      ) : null}
      {delegate.conversationId !== null || delegate.runId !== null ? (
        <DelegationMetadata conversationId={delegate.conversationId} runId={delegate.runId} />
      ) : null}
    </ToolActivityRowShell>
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
