// apps/web/src/features/conversations/components/conversation-detail-header.tsx

import { AlertCircleIcon, CircleDashedIcon, CircleIcon, ShieldAlertIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { conversationAgentLabel, sourceLabel } from "@/features/conversations/format"
import { isRunStatusPolling } from "@/features/conversations/message-parts"
import type { AgentRun, AgentRunStatus, Conversation } from "@/features/conversations/types"
import { formatDateTime } from "@/lib/format"
import { isRecord } from "@/lib/guards"

export function ConversationDetailHeader({
  activeRun,
  conversation,
}: {
  activeRun: AgentRun | null
  conversation: Conversation
}) {
  const scheduleContext =
    conversation.source === "scheduled" ? getScheduleContext(conversation.metadata) : null
  const displayedRunStatus = activeRun?.status ?? conversation.active_run_status

  return (
    <header className="flex flex-col gap-3 p-4">
      <div className="flex flex-col justify-between gap-3 md:flex-row md:items-start">
        <div className="min-w-0">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <Badge variant="outline">{sourceLabel(conversation.source)}</Badge>
            {displayedRunStatus && <RunStatusBadge status={displayedRunStatus} />}
            {conversation.needs_approval && displayedRunStatus !== "awaiting_approval" && (
              <Badge variant="secondary">
                <ShieldAlertIcon data-icon="inline-start" />
                Approval
              </Badge>
            )}
            {conversation.unread && (
              <Badge variant="outline">
                <CircleIcon className="fill-current" data-icon="inline-start" />
                Unread
              </Badge>
            )}
          </div>
          <h2 className="font-heading truncate text-xl font-semibold">
            {conversation.title ?? "Untitled conversation"}
          </h2>
          <p className="text-muted-foreground mt-1 truncate text-sm">
            {conversationAgentLabel(conversation, "No active agent")}
          </p>
          {scheduleContext && (
            <p className="text-muted-foreground mt-1 truncate text-xs">{scheduleContext}</p>
          )}
        </div>
        <div className="text-muted-foreground shrink-0 text-left text-xs md:text-right">
          <p>Last activity</p>
          <p className="text-foreground">
            {formatDateTime(conversation.last_message_at ?? conversation.updated_at)}
          </p>
        </div>
      </div>

      {activeRun && <ActiveRunBanner activeRun={activeRun} />}
    </header>
  )
}

function getScheduleContext(metadata: Record<string, unknown> | null) {
  if (!isRecord(metadata)) {
    return null
  }

  const schedule = metadata["schedule"]
  if (!isRecord(schedule)) {
    return null
  }

  const parts = [
    compactMetadataPart("Schedule", schedule["schedule_id"]),
    compactMetadataPart("Run", schedule["schedule_run_id"]),
    compactMetadataPart("Scheduled", schedule["scheduled_for"], formatDateTime),
  ].filter((part): part is string => part !== null)

  return parts.length > 0 ? parts.join(" · ") : null
}

function compactMetadataPart(
  label: string,
  value: unknown,
  formatter: (value: string) => string = shortIdentifier
) {
  if (typeof value !== "string" || value.length === 0) {
    return null
  }

  return `${label} ${formatter(value)}`
}

function shortIdentifier(value: string) {
  return value.length > 12 ? value.slice(0, 8) : value
}

function ActiveRunBanner({ activeRun }: { activeRun: AgentRun }) {
  if (activeRun.status === "awaiting_approval") {
    return (
      <Alert>
        <ShieldAlertIcon />
        <AlertTitle>Approval required</AlertTitle>
        <AlertDescription>
          This run is waiting for a tool decision before it can continue.
        </AlertDescription>
      </Alert>
    )
  }

  if (activeRun.status === "failed") {
    return (
      <Alert variant="destructive">
        <AlertCircleIcon />
        <AlertTitle>Run failed</AlertTitle>
        <AlertDescription>
          {activeRun.error_message ?? "The agent run ended before completing."}
        </AlertDescription>
      </Alert>
    )
  }

  if (isRunStatusPolling(activeRun.status)) {
    return (
      <Alert>
        <CircleDashedIcon className="animate-spin" />
        <AlertTitle>Agent is working</AlertTitle>
        <AlertDescription>
          New messages will appear here as the run saves progress.
        </AlertDescription>
      </Alert>
    )
  }

  return null
}

function RunStatusBadge({ status }: { status: AgentRunStatus }) {
  if (status === "failed" || status === "cancelled") {
    return <Badge variant="destructive">{statusLabel(status)}</Badge>
  }

  if (status === "awaiting_approval") {
    return <Badge variant="secondary">{statusLabel(status)}</Badge>
  }

  return <Badge>{statusLabel(status)}</Badge>
}

function statusLabel(status: AgentRunStatus) {
  if (status === "awaiting_approval") {
    return "awaiting approval"
  }
  return status
}
