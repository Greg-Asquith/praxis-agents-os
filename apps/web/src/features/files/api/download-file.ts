// apps/web/src/features/files/api/download-file.ts

import type { FileDownloadGrant, FileDownloadRequest } from "../types"
import { apiRequest } from "@/lib/api/client"

type CreateFileDownloadOptions = {
  forceDownload?: boolean
  revisionId?: string
}

export async function createFileDownload(fileId: string, options: CreateFileDownloadOptions = {}) {
  const body: FileDownloadRequest = {
    force_download: options.forceDownload ?? true,
  }
  if (options.revisionId) {
    body.revision_id = options.revisionId
  }

  return apiRequest<FileDownloadGrant>(`/files/${fileId}/download`, {
    body,
    method: "POST",
  })
}
