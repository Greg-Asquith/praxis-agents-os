// apps/web/src/features/files/api/create-folder.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { filesQueryKeys } from "./list-files"
import type { FileFolder } from "../types"
import { apiRequest } from "@/lib/api/client"

type CreateFolderInput = { description?: string | null; name: string }

export function useCreateFolderMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: CreateFolderInput) =>
      apiRequest<FileFolder>("/files/folders", { body: input, method: "POST" }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: filesQueryKeys.folders() })
    },
  })
}
