// apps/web/src/features/knowledge/api/platform-withdraw-document.ts

import {
  mutationOptions,
  useMutation,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query"
import { platformKnowledgeQueryKeys } from "./platform-list-documents"
import { knowledgeQueryKeys } from "./list-documents"
import type { KbDocumentDetail } from "@/features/knowledge/types"
import { apiRequest } from "@/lib/api/client"

export function platformWithdrawDocumentMutationOptions(queryClient: QueryClient) {
  return mutationOptions({
    mutationFn: (documentId: string) =>
      apiRequest<KbDocumentDetail>(`/kb/platform/documents/${documentId}/withdraw`, {
        method: "POST",
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: platformKnowledgeQueryKeys.all }),
        queryClient.invalidateQueries({ queryKey: knowledgeQueryKeys.all }),
      ])
    },
  })
}

export function usePlatformWithdrawDocumentMutation() {
  return useMutation(platformWithdrawDocumentMutationOptions(useQueryClient()))
}
