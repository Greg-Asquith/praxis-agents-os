// apps/web/src/features/conversations/api/update-sharing.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { conversationsQueryKeys } from "@/features/conversations/api/list-conversations"
import {
  clearSharedChat,
  sharedChatQueryOptions,
} from "@/features/conversations/api/get-shared-chat"
import type { ConversationDetail } from "@/features/conversations/types"
import { apiRequest } from "@/lib/api/client"

export function useUpdateSharing(conversationId: string) {
  const queryClient = useQueryClient()
  const detailKey = conversationsQueryKeys.detail(conversationId)
  const sharedKey = sharedChatQueryOptions(conversationId).queryKey
  const messagesKey = conversationsQueryKeys.messages(conversationId)
  const listsKey = conversationsQueryKeys.lists()
  return useMutation({
    onMutate: () => ({ detailKey, sharedKey, messagesKey, listsKey }),
    mutationFn: (visibility: "private" | "workspace") =>
      apiRequest<ConversationDetail>(`/conversations/${conversationId}/sharing`, {
        method: "PUT",
        body: { visibility },
      }),
    onSuccess: async (conversation, _visibility, keys) => {
      const { detailKey, sharedKey, messagesKey, listsKey } = keys
      if (conversation.access === "viewer" && conversation.visibility === "private") {
        await clearSharedChat(queryClient, {
          detail: detailKey,
          messages: messagesKey,
          shared: sharedKey,
        })
      } else {
        await Promise.all([
          queryClient.cancelQueries({ queryKey: sharedKey }),
          queryClient.cancelQueries({ queryKey: detailKey }),
        ])
        queryClient.setQueryData(detailKey, conversation)
        await queryClient.invalidateQueries({ queryKey: sharedKey })
      }
      await queryClient.invalidateQueries({ queryKey: listsKey })
    },
  })
}
