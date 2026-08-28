// apps/web/src/features/knowledge/api/create-document-from-integration.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { knowledgeQueryKeys } from "@/features/knowledge/api/list-documents"
import type {
  KbDocumentDetail,
  KbIntegrationDocumentCreateRequest,
} from "@/features/knowledge/types"
import { apiRequest } from "@/lib/api/client"

export function useCreateDocumentFromIntegrationMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: KbIntegrationDocumentCreateRequest) =>
      apiRequest<KbDocumentDetail>("/kb/documents/from-integration", {
        body: payload,
        method: "POST",
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: knowledgeQueryKeys.lists() })
    },
  })
}
