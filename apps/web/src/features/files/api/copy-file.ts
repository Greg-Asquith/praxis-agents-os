// apps/web/src/features/api/cope-file.ts

import {
  mutationOptions,
  useMutation,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query"

import { filesQueryKeys } from "./list-files"
import type { WorkspaceFile } from "../types"
import { apiRequest } from "@/lib/api/client"

type CopyFileInput = { fileId: string; revisionId: string; requestId: string }

async function copyFile({ fileId, revisionId, requestId }: CopyFileInput) {
  return apiRequest<WorkspaceFile>(`/files/${fileId}/copy`, {
    method: "POST",
    body: { revision_id: revisionId, request_id: requestId },
  })
}

export function copyFileMutationOptions(queryClient: QueryClient) {
  const workspaceKey = filesQueryKeys.workspace()
  return mutationOptions({
    mutationFn: copyFile,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: workspaceKey })
    },
  })
}

export function useCopyFileMutation() {
  return useMutation(copyFileMutationOptions(useQueryClient()))
}
