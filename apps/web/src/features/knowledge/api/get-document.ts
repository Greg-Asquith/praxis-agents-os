// apps/web/src/features/knowledge/api/get-document.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import { knowledgeQueryKeys } from "@/features/knowledge/api/list-documents"
import { hasActiveProcessing } from "@/features/knowledge/status"
import type { KbDocumentDetail } from "@/features/knowledge/types"
import { apiRequest } from "@/lib/api/client"

function documentQueryOptions(documentId: string) {
  return queryOptions({
    queryKey: knowledgeQueryKeys.detail(documentId),
    queryFn: () => apiRequest<KbDocumentDetail>(`/kb/documents/${documentId}`),
    refetchInterval: (query) =>
      query.state.data && hasActiveProcessing([query.state.data]) ? 5_000 : false,
  })
}

export function useDocumentQuery(documentId: string) {
  return useSuspenseQuery(documentQueryOptions(documentId))
}
