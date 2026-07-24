// apps/web/src/features/knowledge/api/create-document-from-file.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { knowledgeQueryKeys } from "@/features/knowledge/api/list-documents"
import type { KbDocumentDetail, KbFileDocumentCreateRequest } from "@/features/knowledge/types"
import { apiRequest } from "@/lib/api/client"

export function useCreateDocumentFromFileMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: KbFileDocumentCreateRequest) =>
      apiRequest<KbDocumentDetail>("/kb/documents/from-file", {
        body: payload,
        method: "POST",
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: knowledgeQueryKeys.lists() })
    },
  })
}
