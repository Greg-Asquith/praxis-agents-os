// apps/web/src/features/conversations/components/delegation-tool-row.tsx

import { approvalActivityIdentity } from "@/lib/tool-activity-identity"

import { use } from "react"
import { Link } from "@tanstack/react-router"
import { BotIcon, ExternalLinkIcon, UsersIcon } from "lucide-react"

import { SharedTranscriptContext } from "@/components/tool-ui/tool-conversation-context"
import {
  ToolApprovalDecisionCard,
  type ToolApprovalDecisionControls,
} from "@/components/tool-ui/approval-card"
import { approvalFallbackFields } from "@/components/tool-ui/approval-fallback-fields"
import { DeclinedResult } from "@/components/tool-ui/declined-result"
import { FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { ToolResultCard, type ToolResultDetail } from "@/components/tool-ui/result-card"
import { Badge } from "@/components/ui/badge"
import { buttonVariants } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { AgentIdentityIcon } from "@/features/agents/components/agent-identity-icon"
import { useAgentIdentityMetadata } from "@/features/agents/use-agent-identity-metadata"
import { MarkdownContent } from "@/components/markdown/markdown-content"
import { AssistantTurnContext } from "@/features/conversations/assistant-turn-context"
import { DelegationActivity } from "@/features/conversations/components/delegation-activity"
import { userMessageBubbleClass } from "@/features/conversations/components/message-shell"
import { ActivityStatusBadge } from "@/features/conversations/components/tool-activity-status"
import { supportIdentifier } from "@/features/conversations/format"
import { delegateAgentSummaries } from "@/features/conversations/delegation-agent-list"
import type { DelegationToolActivity, ToolActivity } from "@/features/conversations/message-parts"
import { useToolPresentations } from "@/features/tools/use-tool-presentations"
import { pluralize } from "@/lib/format"
import { cn } from "@/lib/utils"

const DELEGATE_TO_AGENT_TOOL_NAME = "delegate_to_agent"

type DelegationToolRowProps = {
  activity: ToolActivity
  approvalDecision?: ToolApprovalDecisionControls
  defaultOpen: boolean
  live?: boolean
}

export function DelegateAgentListRow({
  activity,
  defaultOpen,
}: Omit<DelegationToolRowProps, "approvalDecision" | "live">) {
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
              <DelegateAgentIcon agentId={agent.id} name={agent.name} />
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
  live = false,
}: DelegationToolRowProps) {
  const shared = use(SharedTranscriptContext)
  const presentationFor = useToolPresentations()
  const delegate = activity.delegate
  if (!delegate) {
    return null
  }

  const targetLabel = delegate.agentName ?? "Delegate to Agent"
  const presentation = presentationFor(activity.name)
  const toolLabel = presentation?.label ?? activity.name
  if (approvalDecision) {
    const isDelegatedToolApproval = activity.name !== DELEGATE_TO_AGENT_TOOL_NAME
    const fields = presentation?.ui.arg_fields ?? []
    return (
      <ToolApprovalDecisionCard
        activityId={approvalActivityIdentity(activity)}
        approveLabel={isDelegatedToolApproval ? "Approve" : "Approve & Delegate"}
        args={activity.args}
        controls={approvalDecision}
        fallbackFields={approvalFallbackFields(activity.args, fields)}
        fields={fields}
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
        toolName={activity.name}
      />
    )
  }
  const denied = activity.status === "denied"
  const failed =
    activity.status === "failed" ||
    activity.status === "unknown" ||
    delegate.status === "failed" ||
    delegate.status === "unknown"
  const status = denied ? "denied" : failed ? "failed" : delegate.status
  const inProgress = status === "running" || status === "awaiting_approval"
  const heading =
    activity.name === DELEGATE_TO_AGENT_TOOL_NAME
      ? `Conversation with ${targetLabel}`
      : `${targetLabel}: ${toolLabel}`

  return (
    <ToolResultCard
      ariaLabel={heading}
      defaultOpen={defaultOpen || inProgress || failed || denied}
      details={delegationDetails(delegate)}
      heading={<DelegationHeading delegate={delegate}>{heading}</DelegationHeading>}
      trailing={<ActivityStatusBadge liveRunning={live && status === "running"} status={status} />}
    >
      <div className="flex min-w-0 flex-col gap-5">
        {delegate.taskPreview ? <DelegationAsk task={delegate.taskPreview} /> : null}
        <div className="flex min-w-0 flex-col gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <DelegationIdentity delegate={delegate} label={targetLabel} />
            <span className="truncate text-sm font-medium">{targetLabel}</span>
            {status === "running" ? (
              <span className="bg-primary size-1.5 animate-pulse rounded-full motion-reduce:animate-none" />
            ) : null}
          </div>
          {!shared && delegate.conversationId && status !== "denied" ? (
            <DelegationActivity
              conversationId={delegate.conversationId}
              live={status === "running"}
            />
          ) : null}
          <DelegationReply
            activity={activity}
            delegate={delegate}
            status={status}
            targetLabel={targetLabel}
          />
        </div>
        {delegate.conversationId ? (
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <Link
              className={cn(buttonVariants({ variant: "outline", size: "sm" }), "max-w-full")}
              params={{ conversationId: delegate.conversationId }}
              to="/conversations/$conversationId"
              target="_blank"
            >
              <ExternalLinkIcon data-icon="inline-start" />
              Open Full Conversation
            </Link>
          </div>
        ) : null}
      </div>
    </ToolResultCard>
  )
}

// The asking agent is the assistant whose turn contains this row.
function DelegationAsk({ task }: { task: string }) {
  const caller = use(AssistantTurnContext)

  return (
    <div className="flex justify-end">
      <div className="flex max-w-[min(38rem,90%)] min-w-0 flex-col items-end gap-1.5">
        <div className="text-muted-foreground flex min-w-0 items-center gap-1.5 text-xs">
          {caller ? (
            <AgentIdentityIcon
              agentId={caller.agentId}
              decorative
              metadata={caller.metadata}
              name={caller.label}
              size="sm"
            />
          ) : null}
          <span className="text-foreground truncate font-medium">{caller?.label ?? "Agent"}</span>
        </div>
        <div className={cn(userMessageBubbleClass, "min-w-0 whitespace-pre-wrap")}>{task}</div>
      </div>
    </div>
  )
}

function DelegationReply({
  activity,
  delegate,
  status,
  targetLabel,
}: {
  activity: ToolActivity
  delegate: DelegationToolActivity
  status: DelegationToolActivity["status"] | "denied"
  targetLabel: string
}) {
  if (status === "denied") {
    return (
      <DeclinedResult
        description="This delegation was declined, so no work was started."
        reason={activity.decisionReason}
      />
    )
  }
  if (status === "failed" || status === "unknown") {
    return (
      <p className="text-destructive text-sm">
        {delegate.error ?? "The delegated task did not finish. No result was confirmed."}
      </p>
    )
  }
  if (status === "running") {
    return (
      <div aria-busy="true" className="grid gap-2">
        <Skeleton className="h-3.5 w-3/5" />
        <Skeleton className="h-3.5 w-4/5" />
        <Skeleton className="h-3.5 w-2/5" />
        <span className="sr-only">Waiting for {targetLabel} to reply</span>
      </div>
    )
  }
  if (status === "awaiting_approval") {
    return (
      <p className="text-muted-foreground text-sm">
        {targetLabel} needs your approval before it can continue.
      </p>
    )
  }
  if (!delegate.output) {
    return <p className="text-muted-foreground text-sm">{targetLabel} finished without a reply.</p>
  }
  return (
    <div className="min-w-0">
      <MarkdownContent content={delegate.truncated ? `${delegate.output}\n…` : delegate.output} />
    </div>
  )
}

function delegationDetails(delegate: DelegationToolActivity): ToolResultDetail[] {
  return [
    ...(delegate.taskPreview ? [{ label: "Asked", value: delegate.taskPreview }] : []),
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
  // The 20px identity icon fills its line, so give it room above the summary.
  return (
    <span className={cn("inline-flex min-w-0 items-center gap-2", delegate && "py-0.5")}>
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
    <DelegateAgentIcon agentId={delegate.agentId} name={label} />
  ) : (
    <BotIcon className="text-muted-foreground size-4 shrink-0" />
  )
}

function DelegateAgentIcon({ agentId, name }: { agentId: string; name: string }) {
  const shared = use(SharedTranscriptContext)
  const metadata = useAgentIdentityMetadata(shared ? null : agentId)

  return (
    <AgentIdentityIcon agentId={agentId} decorative metadata={metadata} name={name} size="sm" />
  )
}
