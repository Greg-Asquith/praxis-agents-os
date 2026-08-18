// apps/web/src/features/files/api/confirm-file-upload.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { filesQueryKeys } from "./list-files"
import type { WorkspaceFile } from "../types"
import { apiRequest } from "@/lib/api/client"

type ConfirmFileUploadInput = {
  uploadToken: string
  folderId?: string | null
}

export async function confirmFileUpload({ folderId, uploadToken }: ConfirmFileUploadInput) {
  return apiRequest<WorkspaceFile>("/files/uploads/confirm", {
    body: { folder_id: folderId, upload_token: uploadToken },
    method: "POST",
  })
}

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
