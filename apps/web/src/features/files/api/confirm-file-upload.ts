// apps/web/src/features/files/api/confirm-file-upload.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { filesQueryKeys } from "./list-files"
import type { WorkspaceFile } from "../types"
import { apiRequest } from "@/lib/api/client"

type ConfirmFileUploadInput = {
  uploadToken: string
}

async function confirmFileUpload({ uploadToken }: ConfirmFileUploadInput) {
  return apiRequest<WorkspaceFile>("/files/uploads/confirm", {
    body: { upload_token: uploadToken },
    method: "POST",
  })
}

export function useConfirmFileUploadMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: confirmFileUpload,
    onSuccess: async (file) => {
      await queryClient.invalidateQueries({ queryKey: filesQueryKeys.lists() })
      await queryClient.invalidateQueries({ queryKey: filesQueryKeys.detail(file.id) })
      await queryClient.invalidateQueries({ queryKey: filesQueryKeys.revisions(file.id) })
    },
  })
}
