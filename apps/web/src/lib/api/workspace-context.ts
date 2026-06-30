// apps/web/src/lib/api/workspace-context.ts

let activeWorkspaceSlug: string | null = null

export function getActiveWorkspaceSlug() {
  return activeWorkspaceSlug
}

export function setActiveWorkspaceSlug(slug: string | null) {
  activeWorkspaceSlug = slug
}
