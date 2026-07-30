// apps/web/src/lib/workspace.ts

import { setApiRequestHeadersProvider } from "@/lib/api/client"

export const ACTIVE_WORKSPACE_STORAGE_KEY = "praxis.activeWorkspaceSlug"

let activeUserId: string | null = null
let activeWorkspaceSlug: string | null = null

setApiRequestHeadersProvider(() => ({
  "X-Workspace": activeWorkspaceSlug,
}))

export function setActiveUserId(userId: string | null) {
  activeUserId = userId
}

export function setActiveWorkspaceSlug(slug: string | null) {
  activeWorkspaceSlug = slug
}

export function clearActiveWorkspace() {
  activeUserId = null
  activeWorkspaceSlug = null

  if (typeof window !== "undefined") {
    try {
      window.localStorage.removeItem(ACTIVE_WORKSPACE_STORAGE_KEY)
    } catch {
      return
    }
  }
}

export function activeUserQueryScope() {
  return activeUserId ?? "__no_user__"
}

export function activeWorkspaceQueryScope() {
  return activeWorkspaceSlug ?? "__no_workspace__"
}

export function createWorkspaceScopedQueryKeys<Root extends string>(root: Root) {
  const all = [root] as const
  const workspace = () => [...all, activeUserQueryScope(), activeWorkspaceQueryScope()] as const
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
