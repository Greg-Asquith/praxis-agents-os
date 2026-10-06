import { QueryClient } from "@tanstack/react-query"
import { afterEach, describe, expect, it, vi } from "vitest"

import { deleteInvitationMutationOptions } from "@/features/workspaces/api/delete-invitation"
import { workspaceInvitationsQueryKey } from "@/features/workspaces/api/list-invitations"
import type { WorkspaceInvitationsListResponse } from "@/features/workspaces/types"
import { getFetchRequest, jsonResponse, stubFetch } from "../../../support/fetch-stub"

afterEach(() => vi.unstubAllGlobals())

describe("delete workspace invitation", () => {
  it("accepts an empty DELETE response and invalidates only the affected invitation list", async () => {
    const client = new QueryClient()
    const affected = workspaceInvitationsQueryKey("workspace-1")
    const other = workspaceInvitationsQueryKey("workspace-2")
    const unrelated = ["workspaces", "workspace-1", "memberships"]
    for (const key of [affected, other, unrelated]) client.setQueryData(key, { items: [] })
    const fetch = stubFetch(new Response(null, { status: 204 }))
    const mutation = client
      .getMutationCache()
      .build(client, deleteInvitationMutationOptions(client))

    await mutation.execute({ workspaceId: "workspace-1", invitationId: "invitation-2" })

    const { url, init } = getFetchRequest(fetch)
    expect(url.pathname).toBe("/api/v1/workspaces/workspace-1/invitations/invitation-2")
    expect(init.method).toBe("DELETE")
    expect(init.credentials).toBe("include")
    expect(fetch).toHaveBeenCalledOnce()
    expect(client.getQueryState(affected)?.isInvalidated).toBe(true)
    expect(client.getQueryState(other)?.isInvalidated).toBe(false)
    expect(client.getQueryState(unrelated)?.isInvalidated).toBe(false)
    client.clear()
  })

  it("retains cached invitation data when revocation fails", async () => {
    const client = new QueryClient()
    const key = workspaceInvitationsQueryKey("workspace-1")
    const data: WorkspaceInvitationsListResponse = {
      invitations: [
        {
          id: "invitation-2",
          workspace_id: "workspace-1",
          email: "dana@example.com",
          invited_by: "owner-1",
          expires_at: "2026-10-10T09:00:00Z",
          accepted_at: null,
          role: "owner",
          created_at: "2026-09-21T09:00:00Z",
          updated_at: "2026-09-21T09:00:00Z",
          deleted: false,
          deleted_at: null,
        },
      ],
      total: 1,
      limit: 100,
      offset: 0,
    }
    client.setQueryData(key, data)
    stubFetch(jsonResponse({ detail: "Invitation revocation is not permitted." }, { status: 409 }))
    const mutation = client
      .getMutationCache()
      .build(client, deleteInvitationMutationOptions(client))

    await expect(
      mutation.execute({ workspaceId: "workspace-1", invitationId: "invitation-2" })
    ).rejects.toThrow("Invitation revocation is not permitted.")

    expect(client.getQueryState(key)?.isInvalidated).toBe(false)
    expect(client.getQueryData(key)).toEqual(data)
    client.clear()
  })
})
