// apps/web/src/features/knowledge/api/copy-document.ts

import {
  mutationOptions,
  useMutation,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query"
import { knowledgeQueryKeys } from "./list-documents"
import type { KbDocumentDetail } from "@/features/knowledge/types"
import { apiRequest } from "@/lib/api/client"

export function copyDocumentMutationOptions(queryClient: QueryClient) {
  const workspaceKey = knowledgeQueryKeys.workspace()
  return mutationOptions({
    mutationFn: ({
      title,
      contentMd,
      isPrivate = true,
    }: {
      title: string
      contentMd: string
      isPrivate?: boolean
    }) =>
      apiRequest<KbDocumentDetail>("/kb/documents", {
        method: "POST",
        body: { title, content_md: contentMd, is_private: isPrivate },
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: workspaceKey })
    },
  })
}

export function useCopyDocumentMutation() {
  return useMutation(copyDocumentMutationOptions(useQueryClient()))
}
