// apps/web/src/features/knowledge/api/delete-document.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { knowledgeQueryKeys } from "@/features/knowledge/api/list-documents"
import { apiRequest } from "@/lib/api/client"

export function useDeleteDocumentMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (documentId: string) =>
      apiRequest<undefined>(`/kb/documents/${documentId}`, { method: "DELETE" }),
    onSuccess: async (_data, documentId) => {
      queryClient.removeQueries({ queryKey: knowledgeQueryKeys.detail(documentId) })
      await queryClient.invalidateQueries({ queryKey: knowledgeQueryKeys.lists() })
    },
  })
}
