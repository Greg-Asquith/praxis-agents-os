import { QueryClient } from "@tanstack/react-query"
import { afterEach, describe, expect, it, vi } from "vitest"

import { deleteMembershipMutationOptions } from "@/features/workspaces/api/delete-membership"
import { workspaceMembershipsQueryOptions } from "@/features/workspaces/api/list-memberships"
import { getFetchRequest, jsonResponse, stubFetch } from "../../../support/fetch-stub"

afterEach(() => vi.unstubAllGlobals())

describe("delete workspace membership", () => {
  it("accepts an empty DELETE response and invalidates only the affected membership list", async () => {
    const client = new QueryClient()
    const affected = workspaceMembershipsQueryOptions("workspace-1").queryKey
    const other = workspaceMembershipsQueryOptions("workspace-2").queryKey
    const unrelated = ["workspaces", "workspace-1", "invitations"]
    for (const key of [affected, other, unrelated]) client.setQueryData(key, { items: [] })
    const fetch = stubFetch(new Response(null, { status: 204 }))
    const mutation = client.getMutationCache().build(client, deleteMembershipMutationOptions(client))

    await mutation.execute({ workspaceId: "workspace-1", membershipId: "membership-2" })

    const { url, init } = getFetchRequest(fetch)
    expect(url.pathname).toBe("/workspaces/workspace-1/memberships/membership-2")
    expect(init.method).toBe("DELETE")
    expect(init.credentials).toBe("include")
    expect(fetch).toHaveBeenCalledOnce()
    expect(client.getQueryState(affected)?.isInvalidated).toBe(true)
    expect(client.getQueryState(other)?.isInvalidated).toBe(false)
    expect(client.getQueryState(unrelated)?.isInvalidated).toBe(false)
    client.clear()
  })

  it("retains cached membership data when removal fails", async () => {
    const client = new QueryClient()
    const key = workspaceMembershipsQueryOptions("workspace-1").queryKey
    const data = { memberships: [{ id: "membership-2" }] }
    client.setQueryData(key, data)
    stubFetch(jsonResponse({ detail: "The last owner cannot be removed." }, { status: 409 }))
    const mutation = client.getMutationCache().build(client, deleteMembershipMutationOptions(client))

    await expect(
      mutation.execute({ workspaceId: "workspace-1", membershipId: "membership-2" })
    ).rejects.toThrow("The last owner cannot be removed.")

    expect(client.getQueryState(key)?.isInvalidated).toBe(false)
    expect(client.getQueryData(key)).toEqual(data)
    client.clear()
  })
})
