// apps/web/src/features/workspaces/query-keys.ts

import { getActiveWorkspaceSlug } from "@/features/workspaces/workspace-context"

export function activeWorkspaceQueryScope() {
  return getActiveWorkspaceSlug() ?? "__no_workspace__"
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
