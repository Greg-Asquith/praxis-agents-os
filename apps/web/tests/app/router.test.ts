import { QueryClient } from "@tanstack/react-query"
import { describe, expect, it } from "vitest"

import { createAppRouter } from "@/app/router"

describe("conversation route pending behavior", () => {
  it("keeps the current conversation visible while conversation loaders resolve", () => {
    const router = createAppRouter(new QueryClient())

    expect(router.routesByPath["/conversations/new"].options.pendingMs).toBe(Infinity)
    expect(router.routesByPath["/conversations/$conversationId"].options.pendingMs).toBe(Infinity)
    expect(router.options.defaultPendingComponent).toBeDefined()
    expect(router.routesByPath["/integrations"]).toBeDefined()
    expect(router.routesByPath["/context"]).toBeDefined()
  })

  it("keeps only UUID agent preselection values", () => {
    const router = createAppRouter(new QueryClient())
    const validateSearch = router.routesByPath["/conversations/new"].options.validateSearch
    const agentId = "f81d4fae-7dec-4d0a-9658-9e8a9ad91a3d"

    expect(validateSearch).toBeTypeOf("function")
    if (typeof validateSearch !== "function") {
      throw new Error("Expected a function search validator")
    }

    expect(validateSearch({ agent: agentId })).toEqual({ agent: agentId })
    expect(validateSearch({ agent: "not-an-agent-id" })).toEqual({})
    expect(validateSearch({})).toEqual({})
  })
})
