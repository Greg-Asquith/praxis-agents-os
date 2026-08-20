import { QueryClient } from "@tanstack/react-query"
import { afterEach, describe, expect, it, vi } from "vitest"

import { currentUserQueryKey, getOptionalCurrentUser } from "@/features/auth/api/get-current-user"
import { setApiUnauthorizedHandler } from "@/lib/api/client"
import { getFetchRequest, jsonResponse, stubFetch } from "../../support/fetch-stub"

const user = {
  id: "user-a",
  email: "user-a@example.com",
  display_name: "User A",
  avatar_url: null,
  is_active: true,
  is_super_admin: false,
  default_workspace_id: "workspace-a",
  totp_enabled: false,
  created_at: "2026-07-30T00:00:00Z",
  updated_at: "2026-07-30T00:00:00Z",
}

afterEach(() => {
  setApiUnauthorizedHandler(null)
  vi.unstubAllGlobals()
})

describe("optional current user", () => {
  it("revalidates stale cached identity and reports a revoked session", async () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(currentUserQueryKey, user, { updatedAt: 0 })
    const reportSessionLoss = vi.fn()
    setApiUnauthorizedHandler(reportSessionLoss)
    const fetchStub = stubFetch(jsonResponse({ detail: "Session expired" }, { status: 401 }))

    await expect(getOptionalCurrentUser(queryClient)).resolves.toBeNull()

    const { init, url } = getFetchRequest(fetchStub)
    expect(url.href).toBe("http://localhost:8000/api/v1/auth/me")
    expect(init).toMatchObject({ credentials: "include", method: "GET" })
    expect(reportSessionLoss).toHaveBeenCalledOnce()
  })

  it("allows the login route's unauthenticated probe without reporting session loss", async () => {
    const queryClient = new QueryClient()
    const reportSessionLoss = vi.fn()
    setApiUnauthorizedHandler(reportSessionLoss)
    stubFetch(jsonResponse({ detail: "Not authenticated" }, { status: 401 }))

    await expect(getOptionalCurrentUser(queryClient)).resolves.toBeNull()

    expect(reportSessionLoss).not.toHaveBeenCalled()
  })

  it("keeps fresh identity cached within the normal stale window", async () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(currentUserQueryKey, user)
    const fetchStub = stubFetch(jsonResponse(user))

    await expect(getOptionalCurrentUser(queryClient)).resolves.toEqual(user)

    expect(fetchStub).not.toHaveBeenCalled()
  })
})
