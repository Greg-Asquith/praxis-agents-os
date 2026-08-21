// apps/web/src/features/conversations/file-links.ts

import { ApiError } from "@/lib/api/errors"

const WORKSPACE_FILE_ID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const PLACEHOLDER_ORIGIN = "https://praxis.local"

// Models sometimes rewrite the documented `/files?fileId=` link as an absolute URL
// (`https://files?fileId=`, `files?fileId=`, or the app origin); treat those as the same route.
export function workspaceFileIdFromHref(href: string | undefined): string | null {
  if (!href) {
    return null
  }
  let url: URL
  try {
    url = new URL(href, PLACEHOLDER_ORIGIN)
  } catch {
    return null
  }
  if (!isWorkspaceFilesRoute(url)) {
    return null
  }
  const fileId = url.searchParams.get("fileId")
  return fileId !== null && WORKSPACE_FILE_ID.test(fileId) ? fileId : null
}

export async function artifactHrefForFailedFileDownload(
  fileId: string,
  error: unknown,
  loadArtifact: (artifactId: string) => Promise<unknown>
): Promise<string | null> {
  if (!(error instanceof ApiError) || error.status !== 404) {
    return null
  }

  try {
    await loadArtifact(fileId)
  } catch {
    return null
  }

  return `/artifacts/${encodeURIComponent(fileId)}`
}

function isWorkspaceFilesRoute(url: URL): boolean {
  if (url.protocol !== "https:" && url.protocol !== "http:") {
    return false
  }
  if (url.origin === PLACEHOLDER_ORIGIN || isAppOrigin(url.origin)) {
    return url.pathname === "/files"
  }
  return url.hostname === "files" && (url.pathname === "/" || url.pathname === "")
}

function isAppOrigin(origin: string): boolean {
  return typeof window !== "undefined" && origin === window.location.origin
}
