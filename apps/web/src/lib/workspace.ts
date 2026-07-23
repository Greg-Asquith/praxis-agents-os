// apps/web/src/lib/workspace.ts

import { setApiRequestHeadersProvider } from "@/lib/api/client"

let activeWorkspaceSlug: string | null = null

setApiRequestHeadersProvider(() => ({
  "X-Workspace": activeWorkspaceSlug,
}))

export function setActiveWorkspaceSlug(slug: string | null) {
  activeWorkspaceSlug = slug
}

export function activeWorkspaceQueryScope() {
  return activeWorkspaceSlug ?? "__no_workspace__"
}

export function createWorkspaceScopedQueryKeys<Root extends string>(root: Root) {
  const all = [root] as const
  const workspace = () => [...all, activeWorkspaceQueryScope()] as const
  const details = () => [...workspace(), "detail"] as const
  const lists = () => [...workspace(), "list"] as const

  return {
    all,
    workspace,
    details,
    detail: (id: string) => [...details(), id] as const,
    lists,
    list: (params: Record<string, unknown> = {}) => [...lists(), params] as const,
  }
}
