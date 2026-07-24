// apps/web/src/features/knowledge/api/create-document.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { knowledgeQueryKeys } from "@/features/knowledge/api/list-documents"
import type { KbDocumentDetail, KbManualDocumentCreateRequest } from "@/features/knowledge/types"
import { apiRequest } from "@/lib/api/client"

export function useCreateDocumentMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: KbManualDocumentCreateRequest) =>
      apiRequest<KbDocumentDetail>("/kb/documents", { body: payload, method: "POST" }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: knowledgeQueryKeys.lists() })
    },
  })
}
