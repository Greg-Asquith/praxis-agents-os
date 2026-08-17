// apps/web/src/features/conversations/file-links.ts

const WORKSPACE_FILE_ID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

export function workspaceFileIdFromHref(href: string | undefined): string | null {
  if (!href?.startsWith("/files?")) {
    return null
  }
  const url = new URL(href, "https://praxis.local")
  const fileId = url.searchParams.get("fileId")
  return fileId !== null && WORKSPACE_FILE_ID.test(fileId) ? fileId : null
}
