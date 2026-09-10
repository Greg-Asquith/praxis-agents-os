// apps/web/src/features/conversations/routes/conversation-runtime-route.tsx

import { Navigate, Outlet, useParams } from "@tanstack/react-router"
import { useQuery } from "@tanstack/react-query"

import { conversationQueryOptions } from "@/features/conversations/api/get-conversation"
import { ConversationRuntimeProvider } from "@/features/conversations/conversation-runtime-provider"
import { SharedChatUnavailable } from "@/features/conversations/routes/shared-chat-route"

export function ConversationRuntimeRoute() {
  const { conversationId } = useParams({ strict: false })
  const detail = useQuery({
    ...conversationQueryOptions(conversationId ?? ""),
    enabled: Boolean(conversationId),
    retry: false,
  })
  if (detail.data === null) return <SharedChatUnavailable />
  if (conversationId && detail.data?.access === "viewer")
    return (
      <Navigate
        replace
        to="/shared-chats/$workspaceId/$conversationId"
        params={{ workspaceId: detail.data.workspace_id, conversationId }}
      />
    )
  if (conversationId && !detail.data)
    return (
      <p role="status">
        {detail.error
          ? "The chat could not load. Check your connection and try again."
          : "Loading chat…"}
      </p>
    )
  return (
    <ConversationRuntimeProvider>
      <Outlet />
    </ConversationRuntimeProvider>
  )
}
