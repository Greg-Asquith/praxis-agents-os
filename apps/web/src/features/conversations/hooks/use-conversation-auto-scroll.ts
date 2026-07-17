// apps/web/src/features/conversations/hooks/use-conversation-auto-scroll.ts

import { useCallback, useEffect, useMemo, useRef, useState, type UIEventHandler } from "react"

import type { ChatMessageDraft, ToolCallState } from "@/features/conversations/stream/reducer"

export function useConversationAutoScroll({
  approvalCount,
  messageCount,
  pendingMessageCount,
  streamMessages,
  streamToolCalls,
}: {
  approvalCount: number
  messageCount: number
  pendingMessageCount: number
  streamMessages: ChatMessageDraft[]
  streamToolCalls: ToolCallState[]
}) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const shouldPinToBottomRef = useRef(true)
  const [isAwayFromBottom, setIsAwayFromBottom] = useState(false)
  const streamTextSignature = useMemo(
    () => streamMessages.map((message) => `${message.id}:${String(message.text.length)}`).join("|"),
    [streamMessages]
  )
  const streamToolSignature = useMemo(
    () =>
      streamToolCalls.map((toolCall) => `${toolCall.tool_call_id}:${toolCall.status}`).join("|"),
    [streamToolCalls]
  )

  useEffect(() => {
    const element = scrollRef.current
    if (!element) {
      return
    }

    if (shouldPinToBottomRef.current) {
      element.scrollTo({ top: element.scrollHeight })
    }
  }, [approvalCount, messageCount, pendingMessageCount, streamTextSignature, streamToolSignature])

  const handleScroll = useCallback<UIEventHandler<HTMLDivElement>>((event) => {
    const element = event.currentTarget
    const distanceFromBottom = element.scrollHeight - element.scrollTop - element.clientHeight
    shouldPinToBottomRef.current = distanceFromBottom < 80
    setIsAwayFromBottom(distanceFromBottom > 300)
  }, [])

  const scrollToBottom = useCallback(() => {
    const element = scrollRef.current
    if (!element) {
      return
    }
    shouldPinToBottomRef.current = true
    setIsAwayFromBottom(false)
    element.scrollTo({ top: element.scrollHeight })
  }, [])

  return { handleScroll, isAwayFromBottom, scrollRef, scrollToBottom }
}
