// apps/web/src/features/files/api/delete-folder.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { filesQueryKeys } from "./list-files"
import { apiRequest } from "@/lib/api/client"

export function useDeleteFolderMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (folderId: string) =>
      apiRequest<undefined>(`/files/folders/${folderId}`, { method: "DELETE" }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: filesQueryKeys.workspace() })
    },
  })
}
