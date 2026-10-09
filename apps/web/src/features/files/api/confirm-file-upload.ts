// apps/web/src/features/files/api/confirm-file-upload.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { filesQueryKeys } from "./list-files"
import { confirmFileUpload } from "@/lib/api/workspace-file-upload"

export function useConfirmFileUploadMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: confirmFileUpload,
    onSuccess: async (file) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: filesQueryKeys.lists() }),
        queryClient.invalidateQueries({ queryKey: filesQueryKeys.folders() }),
        queryClient.invalidateQueries({ queryKey: filesQueryKeys.detail(file.id) }),
        queryClient.invalidateQueries({ queryKey: filesQueryKeys.revisions(file.id) }),
      ])
    },
  })
}
