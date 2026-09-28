import { QueryClient } from "@tanstack/react-query"
import { afterEach, describe, expect, it, vi } from "vitest"

import { loadAcceptInvitation } from "@/features/workspaces/routes/accept-invitation-loader"
import type { WorkspaceInvitationAcceptResponse } from "@/features/workspaces/types"

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
})
