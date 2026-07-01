// apps/web/src/features/workspaces/workspace-context.ts

let activeWorkspaceSlug: string | null = null

export function getActiveWorkspaceSlug() {
  return activeWorkspaceSlug
}

export function setActiveWorkspaceSlug(slug: string | null) {
  activeWorkspaceSlug = slug
}
