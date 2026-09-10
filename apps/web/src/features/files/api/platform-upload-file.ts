// apps/web/src/features/files/api/platform-upload-file.ts

import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query"
import { platformFilesQueryKeys } from "./platform-list-files"
import { filesQueryKeys } from "./list-files"
import type { FileUploadResult, WorkspaceFile } from "../types"
import { apiRequest } from "@/lib/api/client"
import { uploadFileDirectly } from "@/lib/api/direct-upload"
import { contentTypeForWorkspaceFile } from "@/lib/file"

export function platformUploadFileMutationOptions(
  queryClient: QueryClient,
  publishWhenReady = true
) {
  const queryKey = platformFilesQueryKeys.workspace()
  return {
    mutationFn: async (file: File) => {
      const result = await apiRequest<FileUploadResult>("/files/platform/uploads", {
        method: "POST",
        body: {
          filename: file.name,
          content_type: contentTypeForWorkspaceFile(file),
          size_bytes: file.size,
        },
      })
      if (result.file) return result.file
      if (!result.grant) throw new Error("The upload could not start. Try again.")
      await uploadFileDirectly(result.grant.upload, file, result.grant.max_size_bytes)
      return apiRequest<WorkspaceFile>("/files/platform/uploads/confirm", {
        method: "POST",
        body: { upload_token: result.grant.upload_token, publish_when_ready: publishWhenReady },
      })
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey }),
        queryClient.invalidateQueries({ queryKey: filesQueryKeys.all }),
      ])
    },
  }
}

export function usePlatformUploadFileMutation(publishWhenReady = true) {
  return useMutation(platformUploadFileMutationOptions(useQueryClient(), publishWhenReady))
}
