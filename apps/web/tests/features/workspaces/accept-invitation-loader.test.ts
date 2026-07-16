import { QueryClient } from "@tanstack/react-query"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { loadAcceptInvitation } from "@/features/workspaces/routes/accept-invitation-loader"
import type { WorkspaceInvitationAcceptResponse } from "@/features/workspaces/types"

const { acceptInvitation } = vi.hoisted(() => ({ acceptInvitation: vi.fn() }))

vi.mock("@/features/workspaces/api/accept-invitation", () => ({ acceptInvitation }))

beforeEach(() => {
  acceptInvitation.mockReset()
})

describe("accept invitation loader", () => {
  it("returns the missing-token error without making a request", async () => {
    const result = await loadAcceptInvitation({
      queryClient: new QueryClient(),
      token: undefined,
    })

    expect(result).toEqual({ error: "This invitation link is missing a token.", result: null })
    expect(acceptInvitation).not.toHaveBeenCalled()
  })

  it("deduplicates a single-use token across loader reruns", async () => {
    const accepted = { status: "accepted" } as WorkspaceInvitationAcceptResponse
    acceptInvitation.mockResolvedValue(accepted)
    const queryClient = new QueryClient()

    const first = await loadAcceptInvitation({ queryClient, token: "invitation-token" })
    const second = await loadAcceptInvitation({ queryClient, token: "invitation-token" })

    expect(first).toEqual({ error: null, result: accepted })
    expect(second).toEqual(first)
    expect(acceptInvitation).toHaveBeenCalledTimes(1)
  })
})
