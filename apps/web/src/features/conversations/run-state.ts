// apps/web/src/features/conversations/run-state.ts

import { isRunStatusPolling } from "@/features/conversations/message-parts"
import type { AgentRun } from "@/features/conversations/types"

export function getConversationComposerDisabledReason(activeRun: AgentRun | null) {
  if (!activeRun) {
    return null
  }

  if (activeRun.status === "awaiting_approval") {
    return "Tools require approving before this conversation can continue."
  }

  if (isRunStatusPolling(activeRun.status)) {
    return "The current run is still working."
  }

  return null
}
