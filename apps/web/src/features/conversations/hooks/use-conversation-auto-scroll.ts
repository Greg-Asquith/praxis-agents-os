// apps/web/src/features/conversations/hooks/use-conversation-auto-scroll.ts

import { useEffect, useMemo, useRef } from "react"

import type { ChatMessageDraft } from "@/features/conversations/stream/reducer"

export function useConversationAutoScroll({
  messageCount,
  pendingMessageCount,
  streamMessages,
  streamToolCount,
}: {
  messageCount: number
  pendingMessageCount: number
  streamMessages: ChatMessageDraft[]
  streamToolCount: number
}) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const streamTextSignature = useMemo(
    () => streamMessages.map((message) => `${message.id}:${String(message.text.length)}`).join("|"),
    [streamMessages]
  )

  useEffect(() => {
    const element = scrollRef.current
    if (!element) {
      return
    }

    element.scrollTo({ top: element.scrollHeight })
  }, [messageCount, pendingMessageCount, streamTextSignature, streamToolCount])

  return scrollRef
}
