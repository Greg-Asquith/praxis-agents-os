// apps/web/src/components/shell/workspace-switch-navigation.ts

const WORKSPACE_ENTITY_DETAIL_COLLECTIONS = new Set([
  "agents",
  "artifacts",
  "knowledge",
  "schedules",
  "skills",
])

const COLLECTIONS_WITH_NEW_ROUTES = new Set(["agents", "schedules", "skills"])

export function shouldRedirectHomeForWorkspaceSwitch(
  pathname: string,
  search: Record<string, unknown> = {}
) {
  if (
    pathname === "/files" &&
    (typeof search["fileId"] === "string" || typeof search["folder"] === "string")
  ) {
    return true
  }

  const segments = pathname.split("/").filter(Boolean)
  if (segments.length !== 2) {
    return false
  }

  const [collection, entityId] = segments
  if (collection === "conversations") {
    return true
  }

  return (
    entityId !== undefined &&
    WORKSPACE_ENTITY_DETAIL_COLLECTIONS.has(collection ?? "") &&
    !(entityId === "new" && COLLECTIONS_WITH_NEW_ROUTES.has(collection ?? ""))
  )
}
