// apps/web/src/features/files/api/update-file.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { filesQueryKeys } from "./list-files"
import type { WorkspaceFile } from "../types"
import { apiRequest } from "@/lib/api/client"

type UpdateFileInput = {
  description: string | null
  fileId: string
  name: string
}

async function updateFile({ description, fileId, name }: UpdateFileInput) {
  return apiRequest<WorkspaceFile>(`/files/${fileId}`, {
    body: { description, name },
    method: "PATCH",
  })
}

export function useUpdateFileMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: updateFile,
    onSuccess: async (file) => {
      queryClient.setQueryData(filesQueryKeys.detail(file.id), file)
      await queryClient.invalidateQueries({ queryKey: filesQueryKeys.lists() })
    },
  })
}
