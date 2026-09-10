// apps/web/src/features/knowledge/api/platform-get-document.ts

import { queryOptions } from "@tanstack/react-query"
import { platformKnowledgeQueryKeys } from "./platform-list-documents"
import { hasActiveProcessing } from "@/features/knowledge/status"
import type { KbDocumentDetail } from "@/features/knowledge/types"
import { apiRequest } from "@/lib/api/client"

export function platformDocumentQueryOptions(documentId: string) {
  return queryOptions({
    queryKey: platformKnowledgeQueryKeys.detail(documentId),
    queryFn: () => apiRequest<KbDocumentDetail>(`/kb/platform/documents/${documentId}`),
    staleTime: 0,
    refetchInterval: (query) =>
      query.state.data && hasActiveProcessing([query.state.data]) ? 5_000 : false,
  })
}
