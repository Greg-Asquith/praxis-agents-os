import { QueryClient } from "@tanstack/react-query"
import { afterEach, expect, expectTypeOf, it, vi } from "vitest"

import {
  conversationsQueryKeys,
  conversationsQueryOptions,
} from "@/features/conversations/api/list-conversations"
import type { Conversation, ConversationDetail } from "@/features/conversations/types"
import { setActiveWorkspaceSlug } from "@/lib/workspace"
import { getFetchRequest, jsonResponse, stubFetch } from "../../../support/fetch-stub"

afterEach(() => {
  setActiveWorkspaceSlug(null)
  vi.unstubAllGlobals()
})

it.each([undefined, "mine", "all"] as const)(
  "requests the workspace list with scope %s",
  async (scope) => {
    setActiveWorkspaceSlug("example")
    const fetch = stubFetch(jsonResponse({ conversations: [], total: 0, limit: 50, offset: 10 }))
    const client = new QueryClient()
    await client.fetchQuery(
      conversationsQueryOptions({ limit: 50, offset: 10, ...(scope ? { scope } : {}) })
    )
    const { url, init } = getFetchRequest(fetch)
    expect(url.searchParams.get("scope")).toBe(scope ?? "mine")
    expect(url.searchParams.get("limit")).toBe("50")
    expect(url.searchParams.get("offset")).toBe("10")
    expect(new Headers(init.headers).get("X-Workspace")).toBe("example")
    client.clear()
  }
)

it("separates combined and owner caches and normalises the omitted scope", () => {
  expect(conversationsQueryKeys.list({ limit: 50 })).toEqual(
    conversationsQueryKeys.list({ limit: 50, scope: "mine" })
  )
  expect(conversationsQueryKeys.list({ scope: "all" })).not.toEqual(
    conversationsQueryKeys.list({ scope: "mine" })
  )
  setActiveWorkspaceSlug("first")
  const first = conversationsQueryKeys.list({ scope: "all" })
  setActiveWorkspaceSlug("second")
  expect(first).not.toEqual(conversationsQueryKeys.list({ scope: "all" }))
})

it("preserves owner-only query types", async () => {
  stubFetch(() => jsonResponse({ conversations: [], total: 0, limit: 100, offset: 0 }))
  const client = new QueryClient()
  const own = await client.fetchQuery(conversationsQueryOptions())
  const explicitOwn = await client.fetchQuery(conversationsQueryOptions({ scope: "mine" }))
  const combined = await client.fetchQuery(conversationsQueryOptions({ scope: "all" }))
  expectTypeOf(own.conversations).toEqualTypeOf<Conversation[]>()
  expectTypeOf(explicitOwn.conversations).toEqualTypeOf<Conversation[]>()
  expectTypeOf(combined.conversations).toEqualTypeOf<ConversationDetail[]>()
  expectTypeOf(combined.conversations).not.toEqualTypeOf<Conversation[]>()
  client.clear()
})
