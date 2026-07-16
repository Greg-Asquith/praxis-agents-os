// apps/web/src/features/conversations/components/conversation-detail-header.tsx

import { CalendarClockIcon, CornerDownRightIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { ConversationBadges } from "@/features/conversations/components/conversation-badges"
import { conversationScheduleContext } from "@/features/conversations/format"
import type { AgentRun, Conversation } from "@/features/conversations/types"
import { formatDateTime } from "@/lib/format"

export function ConversationDetailHeader({
  activeRun,
  conversation,
  scheduleLabel,
}: {
  activeRun: AgentRun | null
  conversation: Conversation
  scheduleLabel: string | null
}) {
  const scheduleContext =
    conversation.source === "scheduled" ? conversationScheduleContext(conversation.metadata) : null
  const displayedRunStatus = activeRun?.status ?? conversation.active_run_status
  const showApprovalBadge =
    conversation.needs_approval && displayedRunStatus !== "awaiting_approval"
  const lastActivityAt = conversation.last_message_at ?? conversation.updated_at

  return (
    <header className="px-4 py-3">
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <h2 className="font-heading min-w-0 truncate text-base font-medium">
            {conversation.title ?? "Untitled conversation"}
          </h2>
          {scheduleContext ? (
            <Badge className="max-w-56 shrink-0" variant="outline">
              <CalendarClockIcon aria-hidden="true" data-icon="inline-start" />
              <span className="truncate">Schedule{scheduleLabel ? ` - ${scheduleLabel}` : ""}</span>
            </Badge>
          ) : null}
          {conversation.source === "delegated" ? (
            <span className="text-muted-foreground flex shrink-0 items-center gap-1 text-xs">
              <CornerDownRightIcon aria-hidden="true" className="size-3.5" />
              Started by another agent
            </span>
          ) : null}
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <ConversationBadges
            className="gap-1"
            conversation={conversation}
            runStatus={displayedRunStatus}
            showApproval={showApprovalBadge}
          />
          <div className="text-muted-foreground text-right text-xs">
            {scheduleContext?.scheduledFor ? (
              <p>
                Ran:{" "}
                <span className="text-foreground">
                  {formatDateTime(scheduleContext.scheduledFor)}
                </span>
              </p>
            ) : null}
            <p>
              Updated: <span className="text-foreground">{formatDateTime(lastActivityAt)}</span>
            </p>
          </div>
        </div>
      </div>
    </header>
  )
}
