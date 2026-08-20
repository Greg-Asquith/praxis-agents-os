import { QueryClient } from "@tanstack/react-query"
import { afterEach, describe, expect, it, vi } from "vitest"

import { loadAcceptInvitation } from "@/features/workspaces/routes/accept-invitation-loader"
import type { WorkspaceInvitationAcceptResponse } from "@/features/workspaces/types"
import { ApiError } from "@/lib/api/errors"
import { getFetchRequest, jsonResponse, stubFetch } from "../../support/fetch-stub"

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("accept invitation loader", () => {
  it("returns the missing-token error without making a request", async () => {
    const acceptInvitation = vi.fn()
    const result = await loadAcceptInvitation(
      {
        queryClient: new QueryClient(),
        token: undefined,
      },
      { acceptInvitation }
    )

    expect(result).toEqual({
      error: "This invitation link is missing a token.",
      errorReason: null,
      result: null,
    })
    expect(acceptInvitation).not.toHaveBeenCalled()
  })

  it("deduplicates a single-use token across loader reruns", async () => {
    const accepted = { status: "accepted" } as WorkspaceInvitationAcceptResponse
    const acceptInvitation = vi.fn()
    acceptInvitation.mockResolvedValue(accepted)
    const queryClient = new QueryClient()

    const deps = { acceptInvitation }
    const first = await loadAcceptInvitation({ queryClient, token: "invitation-token" }, deps)
    const second = await loadAcceptInvitation({ queryClient, token: "invitation-token" }, deps)

    expect(first).toEqual({ error: null, errorReason: null, result: accepted })
    expect(second).toEqual(first)
    expect(acceptInvitation).toHaveBeenCalledTimes(1)
  })

  it("preserves the stable wrong-account reason", async () => {
    const acceptInvitation = vi.fn()
    acceptInvitation.mockRejectedValue(
      new ApiError({
        status: 403,
        message: "This invitation belongs to another account.",
        problem: { reason: "invitation_email_mismatch" },
      })
    )

    const result = await loadAcceptInvitation(
      {
        queryClient: new QueryClient(),
        token: "wrong-account-token",
      },
      { acceptInvitation }
    )

    expect(result).toEqual({
      error: "This invitation belongs to another account.",
      errorReason: "invitation_email_mismatch",
      result: null,
    })
  })

  it("uses the production invitation API when dependencies are omitted", async () => {
    const accepted = { status: "accepted" } as WorkspaceInvitationAcceptResponse
    const fetchStub = stubFetch(jsonResponse(accepted))

    await loadAcceptInvitation({
      queryClient: new QueryClient(),
      token: "production-wiring-token",
    })

    expect(fetchStub).toHaveBeenCalledOnce()
    const { init, url } = getFetchRequest(fetchStub)
    expect(url.href).toBe("http://localhost:8000/api/v1/workspaces/invitations/accept")
    expect(init).toMatchObject({ credentials: "include", method: "POST" })
    expect(init.body).toBe(JSON.stringify({ token: "production-wiring-token" }))
  })
})
