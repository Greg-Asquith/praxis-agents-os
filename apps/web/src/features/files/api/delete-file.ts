// apps/web/src/features/files/api/delete-file.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { filesQueryKeys } from "./list-files"
import { apiRequest } from "@/lib/api/client"

type DeleteFileInput = {
  fileId: string
}

async function deleteFile({ fileId }: DeleteFileInput) {
  return apiRequest<undefined>(`/files/${fileId}`, {
    method: "DELETE",
  })
}

export function useDeleteFileMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: deleteFile,
    onSuccess: async (_result, { fileId }) => {
      queryClient.removeQueries({ queryKey: filesQueryKeys.detail(fileId) })
      queryClient.removeQueries({ queryKey: filesQueryKeys.revisions(fileId) })
      queryClient.removeQueries({ queryKey: filesQueryKeys.revisionContents(fileId) })
      await queryClient.invalidateQueries({ queryKey: filesQueryKeys.lists() })
    },
  })
}
