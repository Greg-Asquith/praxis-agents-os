// apps/web/src/features/knowledge/api/platform-create-document.ts

import {
  mutationOptions,
  useMutation,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query"
import { platformKnowledgeQueryKeys } from "./platform-list-documents"
import { knowledgeQueryKeys } from "./list-documents"
import type {
  KbDocumentDetail,
  PlatformKbManualDocumentCreateRequest,
} from "@/features/knowledge/types"
import { apiRequest } from "@/lib/api/client"

function platformCreateDocumentMutationOptions(queryClient: QueryClient) {
  return mutationOptions({
    mutationFn: (payload: PlatformKbManualDocumentCreateRequest) =>
      apiRequest<KbDocumentDetail>("/kb/platform/documents/", { method: "POST", body: payload }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: platformKnowledgeQueryKeys.all }),
        queryClient.invalidateQueries({ queryKey: knowledgeQueryKeys.all }),
      ])
    },
  })
}

export function usePlatformCreateDocumentMutation() {
  return useMutation(platformCreateDocumentMutationOptions(useQueryClient()))
}
