// apps/web/src/features/auth/session-loss.ts

import type { QueryClient } from "@tanstack/react-query"

import { clearCsrfToken } from "@/lib/api/csrf"
import { setApiUnauthorizedHandler } from "@/lib/api/client"
import { clearActiveWorkspace } from "@/lib/workspace"

export function clearAuthenticatedSessionState(queryClient: QueryClient) {
  queryClient.clear()
  clearActiveWorkspace()
  clearCsrfToken()
}

export function installSessionLossHandler(
  queryClient: QueryClient,
  onSessionLost: () => void | Promise<void>
) {
  let isHandlingSessionLoss = false

  const handleSessionLoss = () => {
    clearAuthenticatedSessionState(queryClient)

    if (isHandlingSessionLoss) {
      return
    }

    isHandlingSessionLoss = true
    void Promise.resolve(onSessionLost()).finally(() => {
      isHandlingSessionLoss = false
    })
  }

  setApiUnauthorizedHandler(handleSessionLoss)

  return () => {
    setApiUnauthorizedHandler(null)
  }
}
