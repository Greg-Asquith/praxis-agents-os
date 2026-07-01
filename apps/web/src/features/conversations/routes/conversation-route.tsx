// apps/web/src/features/conversations/routes/conversation-route.tsx

import { useEffect, useMemo } from "react"
import { useParams } from "@tanstack/react-router"
import { useSuspenseQuery } from "@tanstack/react-query"

import { Separator } from "@/components/ui/separator"
import { ConversationDetailHeader } from "@/features/conversations/components/conversation-detail-header"
import { ConversationComposer } from "@/features/conversations/components/conversation-composer"
import { ConversationNotFound } from "@/features/conversations/components/conversation-not-found"
import { MessageList } from "@/features/conversations/components/message-list"
import { useConversationWorkspace } from "@/features/conversations/conversation-workspace-context"
import { conversationActiveRunQueryOptions } from "@/features/conversations/api/get-active-run"
import { conversationMessagesQueryOptions } from "@/features/conversations/api/list-messages"
import { useConversationAutoScroll } from "@/features/conversations/hooks/use-conversation-auto-scroll"
import { useConversationHealLoop } from "@/features/conversations/hooks/use-conversation-heal-loop"
import { getConversationComposerDisabledReason } from "@/features/conversations/run-state"

export function ConversationRoute() {
  const params = useParams({ strict: false })
  const conversationId = requireConversationId(params.conversationId)
  const { clearPersistedPendingMessages, conversations, pendingUserMessages, stream } =
    useConversationWorkspace()
  const messagesQuery = useSuspenseQuery(conversationMessagesQueryOptions(conversationId))
  const activeRunQuery = useSuspenseQuery(conversationActiveRunQueryOptions(conversationId))
  const conversation =
    conversations.find((item) => item.id === conversationId) ??
    (stream.conversation?.id === conversationId ? stream.conversation : null)
  const activeRun = activeRunQuery.data.active_run
  const streamMessages = useMemo(
    () => (stream.conversationId === conversationId ? stream.messages : []),
    [conversationId, stream.conversationId, stream.messages]
  )
  const streamToolCalls = useMemo(
    () => (stream.conversationId === conversationId ? Object.values(stream.toolCalls) : []),
    [stream.conversationId, stream.toolCalls, conversationId]
  )
  const streamApprovals = useMemo(
    () => (stream.conversationId === conversationId ? Object.values(stream.approvals) : []),
    [stream.conversationId, stream.approvals, conversationId]
  )
  useConversationHealLoop(conversationId, activeRun)
  const scrollRef = useConversationAutoScroll({
    messageCount: messagesQuery.data.messages.length,
    pendingMessageCount: pendingUserMessages.length,
    streamMessages,
    streamToolCount: streamToolCalls.length,
  })

  useEffect(() => {
    clearPersistedPendingMessages(messagesQuery.data.messages)
  }, [clearPersistedPendingMessages, messagesQuery.data.messages])

  if (!conversation) {
    return <ConversationNotFound />
  }

  const composerDisabledReason = getConversationComposerDisabledReason(activeRun)
  const streamError =
    stream.conversationId === conversationId ? (stream.error?.message ?? null) : null

  return (
    <div className="flex h-full min-h-[640px] min-w-0 flex-col">
      <ConversationDetailHeader activeRun={activeRun} conversation={conversation} />
      <Separator />

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto p-4">
        <MessageList
          activeRun={activeRun}
          conversationId={conversationId}
          isStreaming={stream.isStreaming && stream.conversationId === conversationId}
          messages={messagesQuery.data.messages}
          pendingUserMessages={pendingUserMessages}
          streamApprovals={streamApprovals}
          streamConversationId={stream.conversationId}
          streamError={streamError}
          streamMessages={streamMessages}
          streamToolCalls={streamToolCalls}
        />
      </div>

      <Separator />
      <footer className="p-3">
        <ConversationComposer
          mode="turn"
          conversationId={conversationId}
          disabledReason={composerDisabledReason}
        />
      </footer>
    </div>
  )
}

function requireConversationId(value: string | undefined) {
  if (!value) {
    throw new Error("Conversation route is missing a conversation id.")
  }
  return value
}
