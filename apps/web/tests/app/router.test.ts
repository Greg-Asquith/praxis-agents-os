import { QueryClient } from "@tanstack/react-query"
import { describe, expect, it } from "vitest"

import { createAppRouter } from "@/app/router"
import { currentUserQueryKey } from "@/features/auth/api/get-current-user"

describe("conversation route pending behavior", () => {
  it("keeps the current conversation visible while conversation loaders resolve", () => {
    const router = createAppRouter(new QueryClient())

    expect(router.routesByPath["/conversations/new"].options.pendingMs).toBe(Infinity)
    expect(router.routesByPath["/conversations/$conversationId"].options.pendingMs).toBe(Infinity)
    expect(router.options.defaultPendingComponent).toBeDefined()
    expect(router.routesByPath["/integrations"]).toBeDefined()
    expect(router.routesByPath["/context"]).toBeDefined()
  })

  it("defers homepage data reads until the active workspace provider renders", () => {
    const router = createAppRouter(new QueryClient())

    expect(router.routesByPath["/"].options.loader).toBeUndefined()
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

  it("preserves an attempted invitation path in the login redirect", async () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(currentUserQueryKey, null)
    const router = createAppRouter(queryClient)
    const beforeLoad = router.routesByPath["/invitations/accept"].parentRoute.options.beforeLoad

    expect(beforeLoad).toBeTypeOf("function")
    if (typeof beforeLoad !== "function") {
      throw new Error("Expected the app route auth guard")
    }
    const beforeLoadContext: Parameters<typeof beforeLoad>[0] = {
      abortController: new AbortController(),
      buildLocation: router.buildLocation,
      cause: "enter",
      context: { queryClient },
      location: {
        external: false,
        hash: "",
        href: "/invitations/accept?token=invite-token",
        pathname: "/invitations/accept",
        publicHref: "/invitations/accept?token=invite-token",
        search: { token: "invite-token" },
        searchStr: "?token=invite-token",
        state: { __TSR_index: 0 },
      },
      matches: [],
      navigate: router.navigate,
      params: {},
      preload: false,
      routeId: router.routesByPath["/invitations/accept"].parentRoute.id,
      search: { token: "invite-token" },
    }

    await expect(beforeLoad(beforeLoadContext)).rejects.toMatchObject({
      options: {
        search: { redirect: "/invitations/accept?token=invite-token" },
        to: "/login",
      },
    })
  })
})
