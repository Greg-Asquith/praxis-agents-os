import { queryOptions, QueryClient } from "@tanstack/react-query"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { currentUserQueryKey } from "@/features/auth/api/get-current-user"
import { installSessionLossHandler } from "@/features/auth/session-loss"
import { reportSessionLoss, setApiUnauthorizedHandler } from "@/lib/api/client"
import {
  ACTIVE_WORKSPACE_STORAGE_KEY,
  activeUserQueryScope,
  activeWorkspaceQueryScope,
  setActiveUserId,
  setActiveWorkspaceSlug,
} from "@/lib/workspace"

const storage = new Map<string, string>()
let writtenCookie = ""

function userAgentsQueryOptions(userId: string) {
  return queryOptions({
    queryKey: ["agents", userId, "acme"] as const,
    queryFn: (): Promise<{ id: string }[]> => Promise.resolve([]),
  })
}

beforeEach(() => {
  storage.clear()
  writtenCookie = ""
  vi.stubGlobal("window", {
    localStorage: {
      getItem: (key: string) => storage.get(key) ?? null,
      removeItem: (key: string) => storage.delete(key),
      setItem: (key: string, value: string) => storage.set(key, value),
    },
  })
  vi.stubGlobal("document", {
    get cookie() {
      return "csrf=session-token"
    },
    set cookie(value: string) {
      writtenCookie = value
    },
  })
})

afterEach(() => {
  setApiUnauthorizedHandler(null)
  vi.unstubAllGlobals()
})

describe("session loss", () => {
  it("clears user-bound state and CSRF material, then revalidates routing", () => {
    const queryClient = new QueryClient()
    const onSessionLost = vi.fn()
    queryClient.setQueryData(currentUserQueryKey, { id: "user-a" })
    queryClient.setQueryData(userAgentsQueryOptions("user-a").queryKey, [{ id: "agent-a" }])
    setActiveUserId("user-a")
    setActiveWorkspaceSlug("acme")
    window.localStorage.setItem(ACTIVE_WORKSPACE_STORAGE_KEY, "acme")
    installSessionLossHandler(queryClient, onSessionLost)

    reportSessionLoss()

    expect(queryClient.getQueryCache().getAll()).toHaveLength(0)
    expect(activeUserQueryScope()).toBe("__no_user__")
    expect(activeWorkspaceQueryScope()).toBe("__no_workspace__")
    expect(window.localStorage.getItem(ACTIVE_WORKSPACE_STORAGE_KEY)).toBeNull()
    expect(writtenCookie).toContain("csrf=; Max-Age=0; Path=/")
    expect(onSessionLost).toHaveBeenCalledOnce()
  })

  it("does not expose the first user's cache after a second user signs in", () => {
    const queryClient = new QueryClient()
    const firstUserAgentsQuery = userAgentsQueryOptions("user-a")
    queryClient.setQueryData(firstUserAgentsQuery.queryKey, [{ id: "agent-a" }])
    setActiveUserId("user-a")
    installSessionLossHandler(queryClient, vi.fn())

    reportSessionLoss()
    setActiveUserId("user-b")
    queryClient.setQueryData(currentUserQueryKey, { id: "user-b" })

    expect(queryClient.getQueryData(firstUserAgentsQuery.queryKey)).toBeUndefined()
    expect(queryClient.getQueryData(currentUserQueryKey)).toEqual({ id: "user-b" })
    expect(activeUserQueryScope()).toBe("user-b")
  })
})
