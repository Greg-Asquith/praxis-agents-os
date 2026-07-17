import { QueryClient } from "@tanstack/react-query"
import { describe, expect, it } from "vitest"

import { createAppRouter } from "@/app/router"

describe("conversation route pending behavior", () => {
  it("keeps the current conversation visible while conversation loaders resolve", () => {
    const router = createAppRouter(new QueryClient())

    expect(router.routesByPath["/conversations/new"].options.pendingMs).toBe(Infinity)
    expect(router.routesByPath["/conversations/$conversationId"].options.pendingMs).toBe(Infinity)
    expect(router.options.defaultPendingComponent).toBeDefined()
  })
})
