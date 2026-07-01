// apps/web/src/features/conversations/components/conversation-detail-header.tsx

import { AlertCircleIcon, CircleDashedIcon, ShieldAlertIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import type { AgentRun, AgentRunStatus, Conversation } from "@/features/conversations/types"
import { isRunStatusPolling } from "@/features/conversations/message-parts"
import { formatDateTime } from "@/lib/format"

export function ConversationDetailHeader({
  activeRun,
  conversation,
}: {
  activeRun: AgentRun | null
  conversation: Conversation
}) {
  return (
    <header className="flex flex-col gap-3 p-4">
      <div className="flex flex-col justify-between gap-3 md:flex-row md:items-start">
        <div className="min-w-0">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <Badge variant="outline">{conversation.source}</Badge>
            {activeRun && <RunStatusBadge status={activeRun.status} />}
          </div>
          <h2 className="font-heading truncate text-xl font-semibold">
            {conversation.title ?? "Untitled conversation"}
          </h2>
          <p className="text-muted-foreground mt-1 truncate text-sm">
            {conversation.agent_slug ?? conversation.active_agent_id ?? "No active agent"}
          </p>
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
