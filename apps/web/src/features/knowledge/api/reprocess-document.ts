// apps/web/src/features/knowledge/api/reprocess-document.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { knowledgeQueryKeys } from "@/features/knowledge/api/list-documents"
import type { KbDocumentDetail } from "@/features/knowledge/types"
import { apiRequest } from "@/lib/api/client"

export function useReprocessDocumentMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (documentId: string) =>
      apiRequest<KbDocumentDetail>(`/kb/documents/${documentId}/reprocess`, {
        method: "POST",
      }),
    onSuccess: async (document) => {
      queryClient.setQueryData(knowledgeQueryKeys.detail(document.id), document)
      await queryClient.invalidateQueries({ queryKey: knowledgeQueryKeys.lists() })
    },
  })
}
