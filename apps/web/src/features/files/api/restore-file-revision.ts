// apps/web/src/features/files/api/restore-file-revision.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { filesQueryKeys } from "./list-files"
import type { WorkspaceFile } from "../types"
import { apiRequest } from "@/lib/api/client"

type RestoreFileRevisionInput = {
  expectedCurrentRevisionId: string
  fileId: string
  revisionId: string
}

async function restoreFileRevision({
  expectedCurrentRevisionId,
  fileId,
  revisionId,
}: RestoreFileRevisionInput) {
  return apiRequest<WorkspaceFile>(`/files/${fileId}/restore`, {
    body: {
      expected_current_revision_id: expectedCurrentRevisionId,
      revision_id: revisionId,
    },
    method: "POST",
  })
}

export function useRestoreFileRevisionMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: restoreFileRevision,
    onSuccess: async (file) => {
      await queryClient.invalidateQueries({ queryKey: filesQueryKeys.lists() })
      await queryClient.invalidateQueries({ queryKey: filesQueryKeys.detail(file.id) })
      await queryClient.invalidateQueries({ queryKey: filesQueryKeys.revisions(file.id) })
      await queryClient.invalidateQueries({ queryKey: filesQueryKeys.revisionContents(file.id) })
    },
  })
}
