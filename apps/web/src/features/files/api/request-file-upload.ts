// apps/web/src/features/files/api/request-file-upload.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { filesQueryKeys } from "./list-files"
import type { FileUploadRequest, FileUploadResult } from "../types"
import { apiRequest } from "@/lib/api/client"

async function requestFileUpload(payload: FileUploadRequest) {
  return apiRequest<FileUploadResult>("/files/uploads", {
    body: payload,
    method: "POST",
  })
}

export function useRequestFileUploadMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: requestFileUpload,
    onSuccess: async (result) => {
      if (result.file) {
        await queryClient.invalidateQueries({ queryKey: filesQueryKeys.lists() })
      }
    },
  })
}
