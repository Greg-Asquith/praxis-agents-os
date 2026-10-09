// apps/web/src/lib/api/workspace-file-upload.ts

import type { FileUploadRequest, FileUploadResult, WorkspaceFile } from "@/features/files/types"
import { apiRequest } from "@/lib/api/client"
import { uploadFileDirectly } from "@/lib/api/direct-upload"
import { contentTypeForWorkspaceFile } from "@/lib/file"

export async function requestFileUpload(payload: FileUploadRequest) {
  return apiRequest<FileUploadResult>("/files/uploads", {
    body: payload,
    method: "POST",
  })
}

export async function confirmFileUpload({
  folderId,
  uploadToken,
}: {
  uploadToken: string
  folderId?: string | null
}) {
  return apiRequest<WorkspaceFile>("/files/uploads/confirm", {
    body: { folder_id: folderId, upload_token: uploadToken },
    method: "POST",
  })
}

/** Uploads a file from the computer into workspace Files, reusing a File with the same content. */
export async function uploadWorkspaceFile(file: File): Promise<WorkspaceFile> {
  const result = await requestFileUpload({
    content_type: contentTypeForWorkspaceFile(file),
    filename: file.name,
    size_bytes: file.size,
  })
  if (result.file) return result.file
  if (!result.grant) throw new Error("Upload grant was not returned.")
  await uploadFileDirectly(result.grant.upload, file, result.grant.max_size_bytes)
  return confirmFileUpload({ uploadToken: result.grant.upload_token })
}
