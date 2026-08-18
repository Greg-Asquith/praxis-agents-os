// apps/web/src/features/files/api/update-folder.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { filesQueryKeys } from "./list-files"
import type { FileFolder } from "../types"
import { apiRequest } from "@/lib/api/client"

type UpdateFolderInput = { description?: string | null; folderId: string; name?: string }

export function useUpdateFolderMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ folderId, ...body }: UpdateFolderInput) =>
      apiRequest<FileFolder>(`/files/folders/${folderId}`, { body, method: "PATCH" }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: filesQueryKeys.workspace() })
    },
  })
}
