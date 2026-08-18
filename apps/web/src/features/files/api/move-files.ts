// apps/web/src/features/files/api/move-files.ts

import {
  mutationOptions,
  useMutation,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query"

import { filesQueryKeys } from "./list-files"
import type { WorkspaceFile } from "../types"
import { apiRequest } from "@/lib/api/client"

type MoveFilesInput = { fileIds: string[]; folderId: string | null }

export function moveFilesMutationOptions(queryClient: QueryClient) {
  return mutationOptions({
    mutationFn: ({ fileIds, folderId }: MoveFilesInput) =>
      apiRequest<{ files: WorkspaceFile[] }>("/files/move", {
        body: { file_ids: fileIds, folder_id: folderId },
        method: "POST",
      }),
    onSuccess: async ({ files }) => {
      for (const file of files) {
        queryClient.setQueryData(filesQueryKeys.detail(file.id), file)
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: filesQueryKeys.lists() }),
        queryClient.invalidateQueries({ queryKey: filesQueryKeys.folders() }),
      ])
    },
  })
}

export function useMoveFilesMutation() {
  const queryClient = useQueryClient()
  return useMutation(moveFilesMutationOptions(queryClient))
}
