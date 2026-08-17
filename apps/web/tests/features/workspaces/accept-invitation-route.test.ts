import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { beforeEach, describe, expect, it, vi } from "vitest"

const { loaderData, logoutMutation, routeSearch } = vi.hoisted(() => {
  const loaderData: { error: string; errorReason: string | null; result: null } = {
    error: "This invitation belongs to another account.",
    errorReason: "invitation_email_mismatch",
    result: null,
  }
  return {
    loaderData,
    logoutMutation: { isPending: false, mutate: vi.fn() },
    routeSearch: { token: "invite-token" },
  }
})

vi.mock("@tanstack/react-router", () => ({
  getRouteApi: () => ({
    useLoaderData: () => loaderData,
    useSearch: () => routeSearch,
  }),
}))
vi.mock("@/features/auth/api/logout", () => ({
  useLogoutMutation: () => logoutMutation,
}))
vi.mock("@/features/workspaces/components/use-active-workspace", () => ({
  useActiveWorkspace: () => ({ setWorkspaceBySlug: vi.fn() }),
}))

import { AcceptInvitationRoute } from "@/features/workspaces/routes/accept-invitation-route"

beforeEach(() => {
  loaderData.errorReason = "invitation_email_mismatch"
  logoutMutation.isPending = false
  logoutMutation.mutate.mockReset()
})

describe("AcceptInvitationRoute", () => {
  it("offers account switching only for an invitation email mismatch", () => {
    expect(renderToStaticMarkup(createElement(AcceptInvitationRoute))).toContain(
      "Sign out and switch account"
    )

    loaderData.errorReason = null

    expect(renderToStaticMarkup(createElement(AcceptInvitationRoute))).not.toContain(
      "Sign out and switch account"
    )
  })
})
