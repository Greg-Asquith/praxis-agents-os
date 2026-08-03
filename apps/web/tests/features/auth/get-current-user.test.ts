import { QueryClient } from "@tanstack/react-query"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { currentUserQueryKey, getOptionalCurrentUser } from "@/features/auth/api/get-current-user"
import { ApiError } from "@/lib/api/errors"

const { apiRequest, reportSessionLoss } = vi.hoisted(() => ({
  apiRequest: vi.fn(),
  reportSessionLoss: vi.fn(),
}))

vi.mock("@/lib/api/client", () => ({
  apiRequest,
  reportSessionLoss,
}))

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

beforeEach(() => {
  apiRequest.mockReset()
  reportSessionLoss.mockReset()
})

describe("optional current user", () => {
  it("revalidates stale cached identity and reports a revoked session", async () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(currentUserQueryKey, user, { updatedAt: 0 })
    apiRequest.mockRejectedValue(
      new ApiError({ status: 401, message: "Session expired", problem: null })
    )

    await expect(getOptionalCurrentUser(queryClient)).resolves.toBeNull()

    expect(apiRequest).toHaveBeenCalledWith("/auth/me", { sessionPolicy: "optional" })
    expect(reportSessionLoss).toHaveBeenCalledOnce()
  })

  it("allows the login route's unauthenticated probe without reporting session loss", async () => {
    const queryClient = new QueryClient()
    apiRequest.mockRejectedValue(
      new ApiError({ status: 401, message: "Not authenticated", problem: null })
    )

    await expect(getOptionalCurrentUser(queryClient)).resolves.toBeNull()

    expect(reportSessionLoss).not.toHaveBeenCalled()
  })

  it("keeps fresh identity cached within the normal stale window", async () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(currentUserQueryKey, user)

    await expect(getOptionalCurrentUser(queryClient)).resolves.toEqual(user)

    expect(apiRequest).not.toHaveBeenCalled()
  })
})
