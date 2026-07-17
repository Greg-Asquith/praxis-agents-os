// apps/web/src/features/conversations/components/delegation-tool-row.tsx

import { Link } from "@tanstack/react-router"
import { ExternalLinkIcon } from "lucide-react"

import { buttonVariants } from "@/components/ui/button"
import { AgentIdentityIcon } from "@/features/agents/components/agent-identity-icon"
import {
  ApprovalDecisionBlock,
  type ToolApprovalDecisionControls,
} from "@/features/conversations/components/approval-decision-block"
import { ToolField } from "@/features/conversations/components/tool-field"
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
import { delegateAgentSummaries } from "@/features/conversations/delegation-agent-list"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { useToolLabels } from "@/features/tools/use-tool-labels"
import { pluralize } from "@/lib/format"
import { cn } from "@/lib/utils"

type DelegationToolRowProps = {
  activity: ToolActivity
  approvalDecision?: ToolApprovalDecisionControls
  compact: boolean
  defaultOpen: boolean
  live: boolean
}

export function DelegateAgentListRow({
  activity,
  compact,
  defaultOpen,
}: Omit<DelegationToolRowProps, "approvalDecision" | "live">) {
  const agents = delegateAgentSummaries(activity.result)
  if (!agents) {
    return null
  }

  const header = (
    <ToolActivityRowHeader
      expandable={agents.length > 0}
      icon={<ActivityStatusIcon fallbackIcon="delegation" status={activity.status} />}
      label="Found Available Agents"
      suffix={
        <ActivityStatusSuffix
          status={activity.status}
          suffix={
            agents.length > 0
              ? `${String(agents.length)} ${pluralize(agents.length, "agent")}`
              : "None Available"
          }
        />
      }
      supportLabel={null}
    />
  )

  return (
    <ToolActivityRowShell
      compact={compact}
      defaultOpen={defaultOpen}
      expandable={agents.length > 0}
      header={header}
    >
      {agents.length > 0 ? (
        <ToolField
          field={{
            key: "agents",
            label: `Agents · ${String(agents.length)}`,
            value: "",
            format: "text",
          }}
        >
          <div className="divide-border -my-1 divide-y">
            {agents.map((agent) => (
              <div className="flex min-w-0 items-center gap-2.5 px-1.5 py-2" key={agent.id}>
                <AgentIdentityIcon agentId={agent.id} decorative name={agent.name} size="sm" />
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium">{agent.name}</span>
                  {agent.description ? (
                    <span className="text-muted-foreground line-clamp-2 block text-xs">
                      {agent.description}
                    </span>
                  ) : null}
                </span>
              </div>
            ))}
          </div>
        </ToolField>
      ) : null}
    </ToolActivityRowShell>
  )
}

export function DelegationToolRow({
  activity,
  approvalDecision,
  compact,
  defaultOpen,
  live,
}: DelegationToolRowProps) {
  const toolLabelFor = useToolLabels()
  const delegate = activity.delegate
  if (!delegate) {
    return null
  }

  const targetLabel = delegate.agentName ?? "Delegate agent"
  const supportLabel = supportIdentifier(delegate.agentId)
  const toolLabel = toolLabelFor(activity.name)
  const expandable =
    Boolean(approvalDecision) ||
    (activity.args !== undefined && activity.args !== null) ||
    Boolean(delegate.taskPreview) ||
    Boolean(delegate.output) ||
    Boolean(delegate.error) ||
    Boolean(delegate.conversationId) ||
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
          liveRunning={live && delegate.status === "running"}
          status={delegate.status}
          suffix={
            delegate.status === "completed"
              ? "Task Complete"
              : delegationStatusSuffix(delegate.status)
          }
        />
      }
      supportLabel={supportLabel}
    />
  )

  if (approvalDecision) {
    const approvalFields = [
      ...(delegate.taskPreview
        ? [
            {
              key: "task",
              label: "Task",
              value: delegate.taskPreview,
              format: "multiline" as const,
            },
          ]
        : []),
      { key: "tool", label: "Tool", value: toolLabel, format: "text" as const },
    ]
    return (
      <ApprovalDecisionBlock
        activity={activity}
        approveLabel="Approve & Delegate"
        controls={approvalDecision}
        fallbackFields={approvalFields}
        iconToken="bot"
        label={toolLabel}
        prompt={`The agent wants to delegate this task to ${targetLabel}.`}
        title={`Delegate to ${targetLabel}`}
      />
    )
  }

  return (
    <ToolActivityRowShell
      compact={compact}
      defaultOpen={shouldOpen}
      expandable={expandable}
      header={header}
    >
      {delegate.taskPreview ? (
        <ToolField
          field={{
            key: "task",
            label: "Task",
            value: delegate.taskPreview,
            format: "multiline",
          }}
        />
      ) : null}
      {delegate.output ? (
        <ToolField
          field={{
            key: "result",
            label: "Result",
            value: delegate.truncated ? `${delegate.output}\n...` : delegate.output,
            format: "multiline",
          }}
        />
      ) : null}
      {delegate.error ? (
        <div className="**:data-[slot=tool-field-label]:text-destructive **:data-[slot=tool-field-well]:border-destructive/40 **:data-[slot=tool-field-well]:bg-destructive/5">
          <ToolField
            field={{ key: "error", label: "Error", value: delegate.error, format: "multiline" }}
          />
        </div>
      ) : null}
      {delegate.pendingApprovalCount > 0 ? (
        <ToolField
          field={{
            key: "approval",
            label: "Approval",
            value: `${String(delegate.pendingApprovalCount)} pending ${pluralize(
              delegate.pendingApprovalCount,
              "request"
            )}`,
            format: "text",
          }}
        />
      ) : null}
      {delegate.conversationId !== null ? (
        <DelegationMetadata conversationId={delegate.conversationId} />
      ) : null}
    </ToolActivityRowShell>
  )
}

function DelegationMetadata({ conversationId }: { conversationId: string }) {
  return (
    <ToolField field={{ key: "transcript", label: "Delegated Work", value: "", format: "text" }}>
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <Link
          className={cn(buttonVariants({ variant: "outline", size: "sm" }), "max-w-full")}
          params={{ conversationId }}
          to="/conversations/$conversationId"
        >
          <ExternalLinkIcon data-icon="inline-start" />
          Open Transcript
        </Link>
      </div>
    </ToolField>
  )
}
