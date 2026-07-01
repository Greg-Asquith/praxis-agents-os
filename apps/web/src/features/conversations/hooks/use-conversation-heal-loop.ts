// apps/web/src/features/conversations/hooks/use-conversation-heal-loop.ts

import { useEffect } from "react"
import { useQueryClient } from "@tanstack/react-query"

import { conversationActiveRunQueryOptions } from "@/features/conversations/api/get-active-run"
import { conversationMessagesQueryOptions } from "@/features/conversations/api/list-messages"
import { isRunStatusPolling } from "@/features/conversations/message-parts"
import type { AgentRun, ConversationActiveRunResponse } from "@/features/conversations/types"

const HEAL_POLL_DELAYS_MS = [250, 750, 1500] as const

export function useConversationHealLoop(conversationId: string, activeRun: AgentRun | null) {
  const queryClient = useQueryClient()

  useEffect(() => {
    if (!isRunStatusPolling(activeRun?.status)) {
      return
    }

    let cancelled = false
    const isCancelled = () => cancelled

    async function pollUntilSettled() {
      let attempt = 0

      while (!isCancelled()) {
        await sleep(healPollDelay(attempt))
        if (isCancelled()) {
          return
        }

        let activeRunResponse: ConversationActiveRunResponse
        try {
          const results = await Promise.all([
            queryClient.fetchQuery({
              ...conversationActiveRunQueryOptions(conversationId),
              staleTime: 0,
            }),
            queryClient.fetchQuery({
              ...conversationMessagesQueryOptions(conversationId),
              staleTime: 0,
            }),
          ])
          activeRunResponse = results[0]
        } catch {
          return
        }

        if (!isRunStatusPolling(activeRunResponse.active_run?.status)) {
          return
        }

        attempt += 1
      }
    }

    void pollUntilSettled()

    return () => {
      cancelled = true
    }
  }, [activeRun?.id, activeRun?.status, conversationId, queryClient])
}

function sleep(delayMs: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, delayMs)
  })
}

function healPollDelay(attempt: number) {
  if (attempt <= 0) {
    return HEAL_POLL_DELAYS_MS[0]
  }
  if (attempt === 1) {
    return HEAL_POLL_DELAYS_MS[1]
  }
  return HEAL_POLL_DELAYS_MS[2]
}
