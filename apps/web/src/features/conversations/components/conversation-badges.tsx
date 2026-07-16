// apps/web/src/features/conversations/components/conversation-badges.tsx

import { CircleIcon, ShieldAlertIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { RunStatusBadge } from "@/features/conversations/components/run-status-badge"
import { sourceLabel } from "@/features/conversations/format"
import type { AgentRunStatus, Conversation } from "@/features/conversations/types"
import { cn } from "@/lib/utils"

export type ConversationSourceVisibility = "always" | "non-direct" | "scheduled" | "none"

type ConversationBadgesProps = {
  className?: string
  conversation: Conversation
  runStatus?: AgentRunStatus | null
  showApproval?: boolean
  sourceVisibility?: ConversationSourceVisibility
}

export function ConversationBadges({
  className,
  conversation,
  runStatus = null,
  showApproval = true,
  sourceVisibility = "non-direct",
}: ConversationBadgesProps) {
  const showSource =
    sourceVisibility === "always" ||
    (sourceVisibility === "non-direct" && conversation.source !== "direct") ||
    (sourceVisibility === "scheduled" && conversation.source === "scheduled")
  const showApprovalBadge = showApproval && conversation.needs_approval
  const hasBadges = showApprovalBadge || conversation.unread || showSource || Boolean(runStatus)

  if (!hasBadges) {
    return null
  }

  return (
    <div className={cn("flex shrink-0 flex-wrap justify-end gap-1", className)}>
      {showApprovalBadge && (
        <Badge variant="warning">
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
      {showSource && <Badge variant="outline">{sourceLabel(conversation.source)}</Badge>}
      {runStatus && <RunStatusBadge status={runStatus} />}
    </div>
  )
}
