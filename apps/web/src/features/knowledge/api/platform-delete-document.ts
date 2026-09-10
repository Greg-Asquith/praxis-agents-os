// apps/web/src/features/knowledge/api/platform-delete-document.ts

import {
  mutationOptions,
  useMutation,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query"
import { platformKnowledgeQueryKeys } from "./platform-list-documents"
import { knowledgeQueryKeys } from "./list-documents"
import { apiRequestNoContent } from "@/lib/api/client"

function platformDeleteDocumentMutationOptions(queryClient: QueryClient) {
  return mutationOptions({
    mutationFn: (documentId: string) =>
      apiRequestNoContent(`/kb/platform/documents/${documentId}`, { method: "DELETE" }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: platformKnowledgeQueryKeys.all }),
        queryClient.invalidateQueries({ queryKey: knowledgeQueryKeys.all }),
      ])
    },
  })
}

export function usePlatformDeleteDocumentMutation() {
  return useMutation(platformDeleteDocumentMutationOptions(useQueryClient()))
}
