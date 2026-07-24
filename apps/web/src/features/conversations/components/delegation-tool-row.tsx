// apps/web/src/features/conversations/components/delegation-tool-row.tsx

import { Link } from "@tanstack/react-router"
import { BotIcon, ExternalLinkIcon, UsersIcon } from "lucide-react"

import {
  ToolApprovalDecisionCard,
  type ApprovalFallbackField,
  type ToolApprovalDecisionControls,
} from "@/components/tool-ui/approval-card"
import { resolveToolField, type ResolvedToolField } from "@/components/tool-ui/field-resolution"
import { fieldLabelClass, fieldWellClass } from "@/components/tool-ui/field-styles"
import { ToolFieldValue } from "@/components/tool-ui/field-value"
import { FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { ToolResultCard } from "@/components/tool-ui/result-card"
import { Badge } from "@/components/ui/badge"
import { buttonVariants } from "@/components/ui/button"
import { AgentIdentityIcon } from "@/features/agents/components/agent-identity-icon"
import { MessageMarkdown } from "@/features/conversations/components/message-markdown"
import { ActivityStatusBadge } from "@/features/conversations/components/tool-activity-status"
import { supportIdentifier } from "@/features/conversations/format"
import { delegateAgentSummaries } from "@/features/conversations/delegation-agent-list"
import type { DelegationToolActivity, ToolActivity } from "@/features/conversations/message-parts"
import { autoUiFields } from "@/features/conversations/tool-ui"
import { useToolPresentations } from "@/features/tools/use-tool-presentations"
import { pluralize } from "@/lib/format"
import { cn } from "@/lib/utils"

const DELEGATE_TO_AGENT_TOOL_NAME = "delegate_to_agent"

type DelegationToolRowProps = {
  activity: ToolActivity
  approvalDecision?: ToolApprovalDecisionControls
  defaultOpen: boolean
}

export function DelegateAgentListRow({
  activity,
  defaultOpen,
}: Omit<DelegationToolRowProps, "approvalDecision">) {
  if (activity.status === "running") {
    return (
      <FanOutSkeleton
        heading={<DelegationHeading icon="list">Available Agents</DelegationHeading>}
        label="Finding available agents…"
        summary="Checking who can help"
      />
    )
  }
  const agents = delegateAgentSummaries(activity.result)
  if (!agents) {
    return null
  }

  const countLabel = `${String(agents.length)} ${pluralize(agents.length, "Agent")}`
  return (
    <ToolResultCard
      ariaLabel="Available delegate agents"
      defaultOpen={defaultOpen}
      details={[{ label: "Available", value: countLabel }]}
      heading={<DelegationHeading icon="list">Available Agents</DelegationHeading>}
      trailing={<Badge variant="success">{countLabel}</Badge>}
    >
      {agents.length > 0 ? (
        <div className="divide-border divide-y" role="list">
          {agents.map((agent) => (
            <div
              className="flex min-w-0 items-center gap-2.5 px-1.5 py-2"
              key={agent.id}
              role="listitem"
            >
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
      ) : (
        <p className="text-muted-foreground px-4 py-6 text-center text-sm">
          No agents are available for delegation.
        </p>
      )}
    </ToolResultCard>
  )
}

export function DelegationToolRow({
  activity,
  approvalDecision,
  defaultOpen,
}: DelegationToolRowProps) {
  const presentationFor = useToolPresentations()
  const delegate = activity.delegate
  if (!delegate) {
    return null
  }

  const targetLabel = delegate.agentName ?? "Delegate agent"
  const presentation = presentationFor(activity.name)
  const toolLabel = presentation?.label ?? activity.name
  if (approvalDecision) {
    const isDelegatedToolApproval = activity.name !== DELEGATE_TO_AGENT_TOOL_NAME
    return (
      <ToolApprovalDecisionCard
        activityId={activity.id}
        approveLabel={isDelegatedToolApproval ? "Approve" : "Approve & Delegate"}
        args={activity.args}
        controls={approvalDecision}
        fallbackFields={
          isDelegatedToolApproval
            ? delegatedToolApprovalFields(activity.args, toolLabel)
            : delegationApprovalFields(delegate, toolLabel)
        }
        fields={isDelegatedToolApproval ? (presentation?.ui.arg_fields ?? []) : []}
        icon={<DelegationIdentity delegate={delegate} label={targetLabel} />}
        label={toolLabel}
        prompt={
          isDelegatedToolApproval
            ? `${targetLabel} wants to use this tool. Review the parameters before approving.`
            : `The agent wants to delegate this task to ${targetLabel}.`
        }
        title={
          isDelegatedToolApproval ? `${targetLabel}: ${toolLabel}` : `Delegate to ${targetLabel}`
        }
      />
    )
  }
  const denied = activity.status === "denied"
  const failed =
    activity.status === "failed" ||
    activity.status === "unknown" ||
    delegate.status === "failed" ||
    delegate.status === "unknown"
  if (!denied && !failed && delegate.status === "running") {
    return (
      <FanOutSkeleton
        heading={<DelegationHeading delegate={delegate}>{targetLabel}</DelegationHeading>}
        label={`Delegating to ${targetLabel}…`}
        summary={delegate.taskPreview ?? "Waiting for the delegated agent"}
      />
    )
  }
  if (!denied && !failed && delegate.status === "awaiting_approval") {
    return (
      <FanOutSkeleton
        heading={<DelegationHeading delegate={delegate}>{targetLabel}</DelegationHeading>}
        label={`Waiting for ${targetLabel} approval…`}
        summary={`${String(delegate.pendingApprovalCount)} pending ${pluralize(
          delegate.pendingApprovalCount,
          "request"
        )}`}
      />
    )
  }

  const details = [
    ...(delegate.agentId
      ? [
          {
            label: "Agent",
            value: supportIdentifier(delegate.agentId) ?? delegate.agentId,
            summary: false,
          },
        ]
      : []),
    ...(delegate.runId
      ? [
          {
            label: "Run",
            value: supportIdentifier(delegate.runId) ?? delegate.runId,
            summary: false,
          },
        ]
      : []),
    ...(delegate.pendingApprovalCount > 0
      ? [
          {
            label: "Approvals",
            value: `${String(delegate.pendingApprovalCount)} pending`,
          },
        ]
      : []),
  ]
  const shouldOpen = defaultOpen || failed || denied

  return (
    <ToolResultCard
      ariaLabel={`Delegation to ${targetLabel}`}
      defaultOpen={shouldOpen}
      details={details}
      heading={<DelegationHeading delegate={delegate}>{targetLabel}</DelegationHeading>}
      trailing={<ActivityStatusBadge status={denied ? "denied" : delegate.status} />}
    >
      <div className="grid min-w-0 gap-3">
        {denied ? (
          <p className="text-muted-foreground text-sm">
            This delegation was declined, so no work was started.
          </p>
        ) : failed ? (
          <p className="text-destructive text-sm">
            {delegate.error ?? "The delegated task did not finish. No result was confirmed."}
          </p>
        ) : null}
        {delegate.taskPreview ? (
          <DelegationField
            field={resolveToolField(
              { key: "task", label: "Task", format: "multiline" },
              delegate.taskPreview
            )}
          />
        ) : null}
        {delegate.output ? (
          <DelegationField
            field={resolveToolField(
              { key: "result", label: "Result", format: "markdown" },
              delegate.truncated ? `${delegate.output}\n…` : delegate.output
            )}
          />
        ) : null}
        {delegate.conversationId ? (
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <Link
              className={cn(buttonVariants({ variant: "outline", size: "sm" }), "max-w-full")}
              params={{ conversationId: delegate.conversationId }}
              to="/conversations/$conversationId"
            >
              <ExternalLinkIcon data-icon="inline-start" />
              Open Transcript
            </Link>
          </div>
        ) : null}
      </div>
    </ToolResultCard>
  )
}

function DelegationHeading({
  children,
  delegate,
  icon = "agent",
}: {
  children: string
  delegate?: DelegationToolActivity
  icon?: "agent" | "list"
}) {
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      {icon === "list" ? (
        <UsersIcon className="text-muted-foreground size-4 shrink-0" />
      ) : delegate ? (
        <DelegationIdentity delegate={delegate} label={children} />
      ) : (
        <BotIcon className="text-muted-foreground size-4 shrink-0" />
      )}
      <span className="truncate">{children}</span>
    </span>
  )
}

function DelegationIdentity({
  delegate,
  label,
}: {
  delegate: DelegationToolActivity
  label: string
}) {
  return delegate.agentId ? (
    <AgentIdentityIcon agentId={delegate.agentId} decorative name={label} size="sm" />
  ) : (
    <BotIcon className="text-muted-foreground size-4 shrink-0" />
  )
}

function DelegationField({ field }: { field: ResolvedToolField | null }) {
  if (!field) {
    return null
  }
  return (
    <div className="grid min-w-0 gap-1">
      <p className={fieldLabelClass}>{field.label}</p>
      <div
        className={cn(
          fieldWellClass,
          "bg-muted/20",
          field.format === "markdown" ? "whitespace-normal" : "whitespace-pre-wrap"
        )}
      >
        <ToolFieldValue
          field={field}
          renderMarkdown={(value) => <MessageMarkdown content={value} />}
        />
      </div>
    </div>
  )
}

function delegationApprovalFields(
  delegate: DelegationToolActivity,
  toolLabel: string
): ApprovalFallbackField[] {
  return [
    resolveToolField({ key: "task", label: "Task", format: "multiline" }, delegate.taskPreview),
    resolveToolField({ key: "tool", label: "Tool", format: "text" }, toolLabel),
  ].filter((field): field is ApprovalFallbackField => field !== null)
}

function delegatedToolApprovalFields(args: unknown, toolLabel: string): ApprovalFallbackField[] {
  const toolField = resolveToolField({ key: "tool", label: "Tool", format: "text" }, toolLabel)
  return [...(toolField ? [toolField] : []), ...autoUiFields(args)]
}
