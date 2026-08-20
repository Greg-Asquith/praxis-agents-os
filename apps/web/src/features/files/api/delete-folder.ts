// apps/web/src/features/files/api/delete-folder.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { filesQueryKeys } from "./list-files"
import { apiRequestNoContent } from "@/lib/api/client"

export function useDeleteFolderMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (folderId: string) =>
      apiRequestNoContent(`/files/folders/${folderId}`, { method: "DELETE" }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: filesQueryKeys.workspace() })
    },
  })
}
