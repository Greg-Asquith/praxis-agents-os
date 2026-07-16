// apps/web/src/features/conversations/conversation-runtime-provider.tsx

import { useCallback, useMemo, useState, type ReactNode } from "react"
import { useNavigate } from "@tanstack/react-router"

import { useConversationsQuery } from "@/features/conversations/api/list-conversations"
import {
  ConversationWorkspaceContext,
  type ConversationWorkspaceContextValue,
} from "@/features/conversations/conversation-workspace-context"
import type { PendingUserMessage } from "@/features/conversations/message-parts"
import { sortConversations } from "@/features/conversations/sort"
import { useAgentStream } from "@/features/conversations/stream/use-agent-stream"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"

export function ConversationRuntimeProvider({ children }: { children: ReactNode }) {
  const { workspace } = useActiveWorkspace()

  return <ConversationRuntimeScope key={workspace.id}>{children}</ConversationRuntimeScope>
}

function ConversationRuntimeScope({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  const { data: conversationsData } = useConversationsQuery({ limit: 100 })
  const [pendingUserMessages, setPendingUserMessages] = useState<PendingUserMessage[]>([])
  const conversations = useMemo(
    () => sortConversations(conversationsData.conversations),
    [conversationsData.conversations]
  )

  const addPendingUserMessage = useCallback((message: PendingUserMessage) => {
    setPendingUserMessages((current) => [...current, message])
  }, [])

  const removePendingUserMessage = useCallback((clientMessageId: string) => {
    setPendingUserMessages((current) =>
      current.filter((message) => message.clientMessageId !== clientMessageId)
    )
  }, [])

  const handleConversationCreated = useCallback(
    (createdConversationId: string) => {
      void navigate({
        to: "/conversations/$conversationId",
        params: { conversationId: createdConversationId },
        replace: true,
      })
    },
    [navigate]
  )

  const stream = useAgentStream({
    onConversationCreated: handleConversationCreated,
  })

  const contextValue: ConversationWorkspaceContextValue = useMemo(
    () => ({
      addPendingUserMessage,
      conversations,
      pendingUserMessages,
      removePendingUserMessage,
      stream,
    }),
    [addPendingUserMessage, conversations, pendingUserMessages, removePendingUserMessage, stream]
  )

  return (
    <ConversationWorkspaceContext value={contextValue}>{children}</ConversationWorkspaceContext>
  )
}
