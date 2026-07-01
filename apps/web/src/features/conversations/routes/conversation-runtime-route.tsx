// apps/web/src/features/conversations/routes/conversation-runtime-route.tsx

import { Outlet } from "@tanstack/react-router"

import { ConversationRuntimeProvider } from "@/features/conversations/conversation-runtime-provider"

export function ConversationRuntimeRoute() {
  return (
    <ConversationRuntimeProvider>
      <Outlet />
    </ConversationRuntimeProvider>
  )
}
