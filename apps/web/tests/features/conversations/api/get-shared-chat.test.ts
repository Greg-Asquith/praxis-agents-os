import { InfiniteQueryObserver, QueryClient, QueryObserver } from "@tanstack/react-query"
import { afterEach, expect, it, vi } from "vitest"

import {
  clearSharedChat,
  sharedChatQueryOptions,
} from "@/features/conversations/api/get-shared-chat"
import { conversationQueryOptions } from "@/features/conversations/api/get-conversation"
import { conversationsQueryKeys } from "@/features/conversations/api/list-conversations"
import { sharedConversationsQueryOptions } from "@/features/conversations/api/list-shared-conversations"
import type { ConversationMessagesResponse } from "@/features/conversations/types"
import { apiRequest } from "@/lib/api/client"
import { ApiError } from "@/lib/api/errors"
import { setActiveUserId, setActiveWorkspaceSlug } from "@/lib/workspace"

vi.mock("@/lib/api/client", () => ({ apiRequest: vi.fn(), setApiRequestHeadersProvider: vi.fn() }))
afterEach(() => vi.resetAllMocks())

const page: ConversationMessagesResponse = {
  messages: [
    {
      id: "new",
      conversation_id: "chat",
      role: "assistant",
      sequence: 5,
      parts: { parts: [] },
      metadata: null,
      error: null,
      tool_name: null,
      client_message_id: null,
      created_at: "2026-09-09T12:00:00Z",
      updated_at: "2026-09-09T12:00:00Z",
    },
  ],
  total: 2,
  has_more: true,
}

it("loads one recent page, advances hidden cursors, and retries earlier failures without losing content", async () => {
  const client = new QueryClient()
  const options = sharedChatQueryOptions("chat")
  vi.mocked(apiRequest).mockResolvedValueOnce(page)
  const observer = new InfiniteQueryObserver(client, options)
  const stop = observer.subscribe(() => undefined)
  await vi.waitFor(() => {
    expect(observer.getCurrentResult().data?.pages).toEqual([page])
  })
  expect(apiRequest).toHaveBeenCalledTimes(1)
  vi.mocked(apiRequest).mockRejectedValueOnce(new TypeError("Network error"))
  await observer.fetchNextPage()
  expect(observer.getCurrentResult().isFetchNextPageError).toBe(true)
  expect(observer.getCurrentResult().data?.pages).toEqual([page])
  vi.mocked(apiRequest).mockResolvedValueOnce({
    ...page,
    messages: [{ ...page.messages[0], id: "old", sequence: 1 }],
    has_more: false,
  })
  await observer.fetchNextPage()
  expect(
    observer
      .getCurrentResult()
      .data?.pages.flatMap((item) => item?.messages.map((message) => message.id))
  ).toEqual(["new", "old"])
  expect(observer.getCurrentResult().hasNextPage).toBe(false)
  expect(vi.mocked(apiRequest).mock.calls[1]?.[1]?.query).toEqual({ before_sequence: 5 })
  stop()
  client.clear()
})

it.each([401, 403, 404])(
  "clears both observed reads after access loss %s without rerender requests or late restoration",
  async (status) => {
    const client = new QueryClient()
    const detailOptions = { ...conversationQueryOptions("chat"), retry: false, staleTime: 0 }
    const options = sharedChatQueryOptions("chat")
    let finish: (value: unknown) => void = () => undefined
    vi.mocked(apiRequest)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finish = resolve
          })
      )
      .mockResolvedValueOnce(page)
    const detail = new QueryObserver(client, detailOptions)
    const messages = new InfiniteQueryObserver(client, options)
    const stopDetail = detail.subscribe(() => undefined)
    const stopMessages = messages.subscribe(() => undefined)
    await vi.waitFor(() => {
      expect(messages.getCurrentResult().data?.pages).toEqual([page])
    })
    vi.mocked(apiRequest).mockRejectedValueOnce(
      new ApiError({ status, message: "Unavailable", problem: null })
    )
    await messages.fetchNextPage()
    expect(messages.getCurrentResult().data?.pages).toContain(null)
    await clearSharedChat(client, {
      detail: detailOptions.queryKey,
      shared: options.queryKey,
      messages: conversationsQueryKeys.messages("chat"),
    })
    finish({ access: "viewer", title: "Late title" })
    detail.getOptimisticResult(client.defaultQueryOptions(detailOptions))
    detail.setOptions(detailOptions)
    messages.getOptimisticResult({
      ...options,
      queryHash: messages.getCurrentQuery().queryHash,
      throwOnError: false,
      refetchOnReconnect: true,
    })
    messages.setOptions(options)
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(apiRequest).toHaveBeenCalledTimes(3)
    expect(detail.getCurrentResult().data).toBeNull()
    expect(messages.getCurrentResult().data?.pages).toEqual([null])
    stopDetail()
    stopMessages()
    client.clear()
  }
)

it("replaces inaccessible detail with null but retains saved detail during a network outage", async () => {
  const client = new QueryClient()
  const options = { ...conversationQueryOptions("chat"), retry: false, staleTime: 0 }
  const saved = { title: "Retained", access: "viewer" }
  vi.mocked(apiRequest).mockResolvedValueOnce(saved)
  await client.fetchQuery(options)
  vi.mocked(apiRequest).mockRejectedValueOnce(new TypeError("Network error"))
  await expect(client.fetchQuery(options)).rejects.toThrow("Network error")
  expect(client.getQueryData(options.queryKey)).toEqual(saved)
  vi.mocked(apiRequest).mockRejectedValueOnce(
    new ApiError({ status: 404, message: "Unavailable", problem: null })
  )
  expect(await client.fetchQuery(options)).toBeNull()
  client.clear()
})

it("reaches all 101 discovery rows and invalidates every page only in its workspace", async () => {
  setActiveUserId("member")
  setActiveWorkspaceSlug("first")
  const client = new QueryClient()
  const rows = Array.from({ length: 101 }, (_, index) => ({ id: String(index) }))
  vi.mocked(apiRequest).mockImplementation((_path, options) => {
    const offset = Number(options?.query?.["offset"] ?? 0)
    return Promise.resolve({
      conversations: rows.slice(offset, offset + 100),
      total: rows.length,
      limit: 100,
      offset,
    })
  })
  const firstOptions = sharedConversationsQueryOptions()
  const secondOptions = sharedConversationsQueryOptions({ offset: 100 })
  const first = await client.fetchQuery(firstOptions)
  const second = await client.fetchQuery(secondOptions)
  expect([...first.conversations, ...second.conversations].map((row) => row.id)).toEqual(
    rows.map((row) => row.id)
  )
  expect(second.total).toBe(101)
  expect(vi.mocked(apiRequest).mock.calls[1]?.[1]?.query).toEqual({
    scope: "workspace_shared",
    limit: 100,
    offset: 100,
  })
  setActiveWorkspaceSlug("second")
  const otherOptions = sharedConversationsQueryOptions()
  await client.fetchQuery(otherOptions)
  await client.invalidateQueries({ queryKey: firstOptions.queryKey.slice(0, -1) })
  expect(client.getQueryState(firstOptions.queryKey)?.isInvalidated).toBe(true)
  expect(client.getQueryState(secondOptions.queryKey)?.isInvalidated).toBe(true)
  expect(client.getQueryState(otherOptions.queryKey)?.isInvalidated).toBe(false)
  client.clear()
})
