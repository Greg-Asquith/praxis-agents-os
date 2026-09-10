import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import { ActiveWorkspaceProvider } from "@/features/workspaces/components/active-workspace-provider"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"

const spies = vi.hoisted(() => ({ update: vi.fn().mockResolvedValue({}), store: vi.fn() }))
vi.mock("@tanstack/react-query", () => ({
  queryOptions: (value: unknown) => value,
  useSuspenseQuery: () => ({ data: { id: "member", default_workspace_id: "first" } }),
}))
vi.mock("@/features/auth/api/update-current-user", () => ({
  useUpdateCurrentUserMutation: () => ({ mutateAsync: spies.update }),
}))
vi.mock("@/features/workspaces/api/list-workspaces", () => ({
  useWorkspacesQuery: () => ({
    data: {
      workspaces: [
        { id: "first", slug: "first" },
        { id: "second", slug: "second" },
      ],
    },
  }),
}))
vi.stubGlobal("window", { localStorage: { getItem: () => null, setItem: spies.store } })

describe("workspace selection persistence", () => {
  it("keeps both stored defaults when selecting a shared-link workspace", () => {
    let context: ReturnType<typeof useActiveWorkspace> | undefined
    function Probe() {
      context = useActiveWorkspace()
      return null
    }
    renderToStaticMarkup(createElement(ActiveWorkspaceProvider, null, createElement(Probe)))
    context?.setWorkspaceBySlug("second", { persist: false })
    context?.setWorkspaceBySlug("first", { persist: false })
    expect(spies.update).not.toHaveBeenCalled()
    expect(spies.store).not.toHaveBeenCalled()
    context?.setWorkspaceBySlug("second")
    expect(spies.update).toHaveBeenCalledWith({ default_workspace_id: "second" })
    expect(spies.store).toHaveBeenCalledTimes(1)
  })
})
