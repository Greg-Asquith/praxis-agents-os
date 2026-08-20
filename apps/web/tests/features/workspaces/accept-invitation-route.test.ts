import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeEach, describe, expect, it, vi } from "vitest"

const { loaderData, routeSearch } = vi.hoisted(() => {
  const loaderData: { error: string; errorReason: string | null; result: null } = {
    error: "This invitation belongs to another account.",
    errorReason: "invitation_email_mismatch",
    result: null,
  }
  return {
    loaderData,
    routeSearch: { token: "invite-token" },
  }
})

vi.mock("@tanstack/react-router", () => ({
  getRouteApi: () => ({
    useLoaderData: () => loaderData,
    useSearch: () => routeSearch,
  }),
}))
vi.mock("@/features/workspaces/components/use-active-workspace", () => ({
  useActiveWorkspace: () => ({ setWorkspaceBySlug: vi.fn() }),
}))

import { AcceptInvitationRoute } from "@/features/workspaces/routes/accept-invitation-route"

const queryClient = new QueryClient()

function renderRoute() {
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client: queryClient },
      createElement(AcceptInvitationRoute)
    )
  )
}

beforeEach(() => {
  loaderData.errorReason = "invitation_email_mismatch"
})

describe("AcceptInvitationRoute", () => {
  it("offers account switching only for an invitation email mismatch", () => {
    expect(renderRoute()).toContain("Sign out and switch account")

    loaderData.errorReason = null

    expect(renderRoute()).not.toContain("Sign out and switch account")
  })
})
