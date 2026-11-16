// apps/web/src/components/tool-ui/workspace-file-preview.ts

import { queryOptions } from "@tanstack/react-query"

import { apiRequest } from "@/lib/api/client"
import { baseFilesQueryKeys } from "@/lib/file-query-keys"
import { isRecord } from "@/lib/guards"

// Preview grants last 10 minutes; refetch well before one expires.
const PREVIEW_STALE_MS = 4 * 60 * 1000

// Keyed by revision, so a replaced File never shows its newer bytes in place of these.
export function workspaceFilePreviewQueryOptions(fileId: string, revisionId: string | null) {
  return queryOptions({
    queryKey: [...baseFilesQueryKeys.detail(fileId), "preview", revisionId ?? "current"],
    queryFn: () =>
      apiRequest<unknown>(
        revisionId
          ? `/files/${fileId}/preview?revision_id=${encodeURIComponent(revisionId)}`
          : `/files/${fileId}/preview`,
        { method: "POST" }
      ),
    staleTime: PREVIEW_STALE_MS,
    retry: 1,
  })
}

export function workspaceFilePreviewUrl(grant: unknown): string | null {
  const preview = isRecord(grant) ? grant["preview"] : null
  const url = isRecord(preview) ? preview["url"] : null
  return typeof url === "string" && url ? url : null
}

export type WorkspaceMediaKind = "image" | "video" | "audio"

export function workspaceMediaKind(contentType: string): WorkspaceMediaKind | null {
  const family = contentType.split("/")[0]?.trim().toLowerCase()
  return family === "image" || family === "video" || family === "audio" ? family : null
}
