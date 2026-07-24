// apps/web/src/features/knowledge/api/create-document-from-url.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { knowledgeQueryKeys } from "@/features/knowledge/api/list-documents"
import type { KbDocumentDetail, KbUrlDocumentCreateRequest } from "@/features/knowledge/types"
import { apiRequest } from "@/lib/api/client"

export function useCreateDocumentFromUrlMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: KbUrlDocumentCreateRequest) =>
      apiRequest<KbDocumentDetail>("/kb/documents/from-url", {
        body: payload,
        method: "POST",
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: knowledgeQueryKeys.lists() })
    },
  })
}
