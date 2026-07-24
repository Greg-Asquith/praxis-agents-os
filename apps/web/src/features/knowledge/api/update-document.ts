// apps/web/src/features/knowledge/api/update-document.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { knowledgeQueryKeys } from "@/features/knowledge/api/list-documents"
import type { KbDocumentDetail, KbDocumentUpdateRequest } from "@/features/knowledge/types"
import { apiRequest } from "@/lib/api/client"

type UpdateDocumentInput = {
  documentId: string
  payload: KbDocumentUpdateRequest
}

export function useUpdateDocumentMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ documentId, payload }: UpdateDocumentInput) =>
      apiRequest<KbDocumentDetail>(`/kb/documents/${documentId}`, {
        body: payload,
        method: "PATCH",
      }),
    onSuccess: async (document) => {
      queryClient.setQueryData(knowledgeQueryKeys.detail(document.id), document)
      await queryClient.invalidateQueries({ queryKey: knowledgeQueryKeys.lists() })
    },
  })
}
