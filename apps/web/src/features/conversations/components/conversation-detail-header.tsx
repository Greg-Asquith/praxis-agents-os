// apps/web/src/features/conversations/components/conversation-detail-header.tsx

import { ConversationBadges } from "@/features/conversations/components/conversation-badges"
import { conversationAgentLabel, supportIdentifier } from "@/features/conversations/format"
import type { AgentRun, Conversation } from "@/features/conversations/types"
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
  const showApprovalBadge =
    conversation.needs_approval && displayedRunStatus !== "awaiting_approval"

  return (
    <header className="flex flex-col gap-3 p-4">
      <div className="flex flex-col justify-between gap-3 md:flex-row md:items-start">
        <div className="min-w-0">
          <ConversationBadges
            className="mb-2 justify-start gap-2"
            conversation={conversation}
            runStatus={displayedRunStatus}
            showApproval={showApprovalBadge}
            sourceVisibility="non-direct"
          />
          <h2 className="font-heading truncate text-xl font-semibold">
            {conversation.title ?? "Untitled conversation"}
          </h2>
          <p className="text-muted-foreground mt-1 truncate text-sm">
            {conversationAgentLabel(conversation, "No active agent")}
          </p>
          {scheduleContext && (
            <div className="text-muted-foreground mt-1 text-xs">
              <p className="truncate">{scheduleContext.label}</p>
              {scheduleContext.supportDetails.length > 0 && (
                <details className="mt-1">
                  <summary className="hover:text-foreground cursor-pointer">
                    Support details
                  </summary>
                  <dl className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
                    {scheduleContext.supportDetails.map((detail) => (
                      <div className="flex min-w-0 gap-1" key={detail.label}>
                        <dt>{detail.label}</dt>
                        <dd className="font-mono">{detail.value}</dd>
                      </div>
                    ))}
                  </dl>
                </details>
              )}
            </div>
          )}
        </div>
        <div className="text-muted-foreground shrink-0 text-left text-xs md:text-right">
          <p>Last Updated</p>
          <p className="text-foreground">
            {formatDateTime(conversation.last_message_at ?? conversation.updated_at)}
          </p>
        </div>
      </div>
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

  const scheduledFor =
    typeof schedule["scheduled_for"] === "string"
      ? `Scheduled for ${formatDateTime(schedule["scheduled_for"])}`
      : "Scheduled conversation"
  const supportDetails = [
    supportMetadataPart("Schedule", schedule["schedule_id"]),
    supportMetadataPart("Run", schedule["schedule_run_id"]),
  ].filter((part): part is { label: string; value: string } => part !== null)

  return {
    label: scheduledFor,
    supportDetails,
  }
}

function supportMetadataPart(label: string, value: unknown) {
  if (typeof value !== "string" || value.length === 0) {
    return null
  }

  const identifier = supportIdentifier(value)
  return identifier ? { label, value: identifier } : null
}
