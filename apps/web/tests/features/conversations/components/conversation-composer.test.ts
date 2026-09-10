import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { expect, it, vi } from "vitest"

import { ConversationComposer } from "@/features/conversations/components/conversation-composer"
import type { Agent } from "@/features/agents/types"

vi.mock("@/features/conversations/conversation-workspace-context", () => ({
  useConversationWorkspace: () => ({ stream: { isStreaming: false } }),
}))
vi.mock("@/features/conversations/components/conversation-context-picker", () => ({
  NewConversationContextPicker: () => null,
  ConversationContextPicker: () => null,
}))
vi.mock("@/features/agents/components/agent-identity-icon", () => ({
  AgentIdentityIcon: () => null,
}))

it("starts with a removable Platform attachment and waits for a message", () => {
  const client = new QueryClient()
  const html = renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client },
      createElement(ConversationComposer, {
        mode: "create",
        agents: [{ id: "agent-1", name: "Assistant", is_active: true } as Agent],
        modelCatalog: { models: [], providers: [], defaults: { agent_model: null } },
        initialAttachment: {
          fileId: "file-1",
          name: "Policy.txt",
          mediaType: "text/plain",
          sizeBytes: 120,
          scope: "platform",
        },
      })
    )
  )
  expect(html).toContain("Policy.txt")
  expect(html).toContain("Platform")
  expect(html).toContain('aria-label="Remove Policy.txt"')
  expect(html).toMatch(
    /<button[^>]*(?:disabled=""[^>]*aria-label="Send"|aria-label="Send"[^>]*disabled="")/
  )
  client.clear()
})
