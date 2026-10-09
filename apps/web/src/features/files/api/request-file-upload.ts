// apps/web/src/features/files/api/request-file-upload.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { filesQueryKeys } from "./list-files"
import { requestFileUpload } from "@/lib/api/workspace-file-upload"

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
