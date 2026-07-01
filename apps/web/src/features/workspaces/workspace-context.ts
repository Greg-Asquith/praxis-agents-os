// apps/web/src/features/workspaces/workspace-context.ts

import { setApiRequestHeadersProvider } from "@/lib/api/client"

let activeWorkspaceSlug: string | null = null

setApiRequestHeadersProvider(() => ({
  "X-Workspace": activeWorkspaceSlug,
}))

export function getActiveWorkspaceSlug() {
  return activeWorkspaceSlug
}

export function setActiveWorkspaceSlug(slug: string | null) {
  activeWorkspaceSlug = slug
}
