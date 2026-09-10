// apps/web/src/features/knowledge/api/platform-update-document.ts

import {
  mutationOptions,
  useMutation,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query"
import { platformKnowledgeQueryKeys } from "./platform-list-documents"
import { knowledgeQueryKeys } from "./list-documents"
import type { KbDocumentDetail, PlatformKbDocumentUpdateRequest } from "@/features/knowledge/types"
import { apiRequest } from "@/lib/api/client"

function platformUpdateDocumentMutationOptions(queryClient: QueryClient) {
  return mutationOptions({
    mutationFn: ({
      documentId,
      payload,
    }: {
      documentId: string
      payload: PlatformKbDocumentUpdateRequest
    }) =>
      apiRequest<KbDocumentDetail>(`/kb/platform/documents/${documentId}`, {
        method: "PATCH",
        body: payload,
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: platformKnowledgeQueryKeys.all }),
        queryClient.invalidateQueries({ queryKey: knowledgeQueryKeys.all }),
      ])
    },
  })
}

export function usePlatformUpdateDocumentMutation() {
  return useMutation(platformUpdateDocumentMutationOptions(useQueryClient()))
}
