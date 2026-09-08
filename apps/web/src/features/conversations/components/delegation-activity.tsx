// apps/web/src/features/conversations/components/delegation-activity.tsx

import { Fragment, use, useMemo } from "react"
import { useQuery } from "@tanstack/react-query"

import { ToolConversationContext } from "@/components/tool-ui/tool-conversation-context"
import { conversationMessagesQueryOptions } from "@/features/conversations/api/list-messages"
import { ToolCallRowRendererContext } from "@/features/conversations/components/tool-call-row-renderer"
import { delegateToolActivities } from "@/features/conversations/delegation-activity"
import { toolActivityIdentity } from "@/features/conversations/message-parts"

const LIVE_REFRESH_MS = 3_000

// The parent stream never carries the child run's tool calls, so the card reads
// them from the delegate's own conversation and refreshes while it is working.
export function DelegationActivity({
  conversationId,
  live,
}: {
  conversationId: string
  live: boolean
}) {
  const renderToolCallRow = use(ToolCallRowRendererContext)
  const { data } = useQuery({
    ...conversationMessagesQueryOptions(conversationId),
    refetchInterval: live ? LIVE_REFRESH_MS : false,
  })
  const activities = useMemo(
    () => (data ? delegateToolActivities(data.messages, live) : []),
    [data, live]
  )

  if (!renderToolCallRow || activities.length === 0) {
    return null
  }

  return (
    <ToolConversationContext value={conversationId}>
      <div className="flex min-w-0 flex-col gap-1.5">
        {activities.map((activity) => (
          <Fragment key={toolActivityIdentity(activity.agentRunId, activity.id)}>
            {renderToolCallRow({ activity, compact: true, live })}
          </Fragment>
        ))}
      </div>
    </ToolConversationContext>
  )
}
