import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider, QueryObserver } from "@tanstack/react-query"
import { afterEach, describe, expect, it, vi } from "vitest"

import { conversationQueryOptions } from "@/features/conversations/api/get-conversation"
import { useUpdateSharing } from "@/features/conversations/api/update-sharing"
import { sharedChatQueryOptions } from "@/features/conversations/api/get-shared-chat"
import { conversationsQueryKeys } from "@/features/conversations/api/list-conversations"
import type { SharedConversation } from "@/features/conversations/types"
import { apiRequest } from "@/lib/api/client"
import { setActiveUserId, setActiveWorkspaceSlug } from "@/lib/workspace"

vi.mock("@/lib/api/client", () => ({ apiRequest: vi.fn(), setApiRequestHeadersProvider: vi.fn() }))
afterEach(() => vi.resetAllMocks())

const revoked: SharedConversation = {
  access: "viewer",
  id: "chat",
  workspace_id: "workspace",
  title: "Shared answer",
  source: "direct",
  agent_name: null,
  owner_name: "Owner",
  visibility: "private",
  active_run_status: null,
  created_at: "2026-09-09T12:00:00Z",
  updated_at: "2026-09-09T12:00:00Z",
  last_message_at: null,
  capabilities: { can_reply: false, can_manage_sharing: false, can_stop_sharing: false },
}

describe("sharing mutation cache lifecycle", () => {
  it("revokes a manager's viewer and cancels a late read in its original workspace", async () => {
    setActiveUserId("manager")
    setActiveWorkspaceSlug("original")
    const client = new QueryClient()
    const options = sharedChatQueryOptions("chat")
    const messagesKey = conversationsQueryKeys.messages("chat")
    client.setQueryData(messagesKey, { messages: ["retained transcript"] })
    let mutation: ReturnType<typeof useUpdateSharing> | undefined
    function Probe() {
      mutation = useUpdateSharing("chat")
      return null
    }
    renderToStaticMarkup(createElement(QueryClientProvider, { client }, createElement(Probe)))
    let finish: (value: unknown) => void = () => undefined
    vi.mocked(apiRequest)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finish = resolve
          })
      )
      .mockResolvedValueOnce(revoked)
    const lateRead = client.fetchInfiniteQuery(options).catch(() => null)
    const request = mutation?.mutateAsync("private")
    setActiveWorkspaceSlug("another")
    await request
    expect(client.getQueryData(options.queryKey)?.pages).toEqual([null])
    expect(client.getQueryData(messagesKey)).toBeUndefined()
    finish({ ...revoked, visibility: "workspace" })
    await lateRead
    expect(client.getQueryData(options.queryKey)?.pages).toEqual([null])
    expect(client.getQueryData(sharedChatQueryOptions("chat").queryKey)).toBeUndefined()
    expect(vi.mocked(apiRequest).mock.calls[1]).toEqual([
      "/conversations/chat/sharing",
      { method: "PUT", body: { visibility: "private" } },
    ])
    client.clear()
  })
})

it.each(["workspace", "private"] as const)(
  "keeps successful %s sharing state after an observed stale detail response",
  async (visibility) => {
    setActiveUserId("owner")
    setActiveWorkspaceSlug("original")
    const client = new QueryClient()
    const detailOptions = { ...conversationQueryOptions("chat"), staleTime: 0 }
    const previous: SharedConversation = {
      ...revoked,
      visibility: visibility === "workspace" ? "private" : "workspace",
    }
    const authoritative = {
      ...revoked,
      access: "owner",
      visibility,
      capabilities: {
        can_reply: true,
        can_manage_sharing: true,
        can_stop_sharing: visibility === "workspace",
      },
    }
    client.setQueryData(detailOptions.queryKey, previous)
    let finish: (value: unknown) => void = () => undefined
    vi.mocked(apiRequest)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finish = resolve
          })
      )
      .mockResolvedValueOnce(authoritative)
    const observer = new QueryObserver(client, detailOptions)
    const unsubscribe = observer.subscribe(() => undefined)
    let mutation: ReturnType<typeof useUpdateSharing> | undefined
    function Probe() {
      mutation = useUpdateSharing("chat")
      return null
    }
    renderToStaticMarkup(createElement(QueryClientProvider, { client }, createElement(Probe)))
    const request = mutation?.mutateAsync(visibility)
    await vi.waitFor(() => {
      expect(apiRequest).toHaveBeenCalledTimes(2)
    })
    setActiveWorkspaceSlug("another")
    // An updated hook must not redirect the in-flight mutation's cache writes.
    renderToStaticMarkup(createElement(QueryClientProvider, { client }, createElement(Probe)))
    await request
    finish(previous)
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(client.getQueryData(detailOptions.queryKey)).toEqual(authoritative)
    expect(observer.getCurrentResult().data).toEqual(authoritative)
    expect(client.getQueryData(conversationQueryOptions("chat").queryKey)).toBeUndefined()
    unsubscribe()
    client.clear()
  }
)
