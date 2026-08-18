// apps/web/src/features/files/api/update-file.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { filesQueryKeys } from "./list-files"
import type { WorkspaceFile } from "../types"
import { apiRequest } from "@/lib/api/client"

type UpdateFileInput = {
  description?: string | null
  fileId: string
  folderId?: string | null
  name?: string
}

async function updateFile({ description, fileId, folderId, name }: UpdateFileInput) {
  return apiRequest<WorkspaceFile>(`/files/${fileId}`, {
    body: { description, folder_id: folderId, name },
    method: "PATCH",
  })
}

export function useUpdateFileMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: updateFile,
    onSuccess: async (file) => {
      queryClient.setQueryData(filesQueryKeys.detail(file.id), file)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: filesQueryKeys.lists() }),
        queryClient.invalidateQueries({ queryKey: filesQueryKeys.folders() }),
      ])
    },
  })
}
