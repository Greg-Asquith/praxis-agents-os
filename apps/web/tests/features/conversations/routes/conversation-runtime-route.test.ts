import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type * as ReactQuery from "@tanstack/react-query"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { expect, it, vi } from "vitest"

import { ConversationRuntimeRoute } from "@/features/conversations/routes/conversation-runtime-route"

const state = vi.hoisted(() => ({ unavailable: false, params: {} }))
vi.mock("@tanstack/react-router", () => ({
  useParams: () => ({ conversationId: "chat" }),
  Outlet: () => "Owner detail",
  Navigate: ({ params }: { params: object }) => {
    state.params = params
    return "Canonical shared route"
  },
}))
vi.mock("@tanstack/react-query", async (importOriginal) => ({
  ...(await importOriginal<typeof ReactQuery>()),
  useQuery: () => ({
    data: state.unavailable
      ? null
      : { access: "viewer", workspace_id: "workspace", capabilities: { can_reply: true } },
  }),
}))
vi.mock("@/features/conversations/conversation-runtime-provider", () => ({
  ConversationRuntimeProvider: () => {
    throw new Error("Owner runtime must not mount")
  },
}))
vi.mock("@/features/conversations/routes/shared-chat-route", () => ({
  SharedChatUnavailable: () => "Chat unavailable",
}))

function renderRoute() {
  const client = new QueryClient()
  const html = renderToStaticMarkup(
    createElement(QueryClientProvider, { client }, createElement(ConversationRuntimeRoute))
  )
  client.clear()
  return html
}

it("redirects a viewer to the canonical shared route without mounting owner runtime", () => {
  expect(renderRoute()).toBe("Canonical shared route")
  expect(state.params).toEqual({ workspaceId: "workspace", conversationId: "chat" })
})

it("keeps unavailable detail out of owner runtime on every render", () => {
  state.unavailable = true
  expect(renderRoute()).toBe("Chat unavailable")
  expect(renderRoute()).toBe("Chat unavailable")
  state.unavailable = false
})
