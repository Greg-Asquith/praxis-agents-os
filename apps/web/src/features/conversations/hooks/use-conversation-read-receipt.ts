// apps/web/src/features/conversations/hooks/use-conversation-read-receipt.ts

import { useEffect, useRef } from "react"

import { useMarkConversationReadMutation } from "@/features/conversations/api/list-conversations"

export function useConversationReadReceipt({
  conversationId,
  unread,
}: {
  conversationId: string
  unread: boolean
}) {
  const { mutate: markConversationRead } = useMarkConversationReadMutation()
  const pendingMarkReadConversationIdRef = useRef<string | null>(null)

  useEffect(() => {
    if (!unread) {
      if (pendingMarkReadConversationIdRef.current === conversationId) {
        pendingMarkReadConversationIdRef.current = null
      }
      return
    }

    if (pendingMarkReadConversationIdRef.current === conversationId) {
      return
    }

    pendingMarkReadConversationIdRef.current = conversationId
    markConversationRead(conversationId, {
      onError: () => {
        pendingMarkReadConversationIdRef.current = null
      },
    })
  }, [conversationId, markConversationRead, unread])
}
