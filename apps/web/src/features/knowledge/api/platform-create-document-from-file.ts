// apps/web/src/features/knowledge/api/platform-create-document-from-file.ts

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
  PlatformKbFileDocumentCreateRequest,
} from "@/features/knowledge/types"
import { apiRequest } from "@/lib/api/client"

export function platformCreateDocumentFromFileMutationOptions(queryClient: QueryClient) {
  return mutationOptions({
    mutationFn: (payload: PlatformKbFileDocumentCreateRequest) =>
      apiRequest<KbDocumentDetail>("/kb/platform/documents/from-file", {
        method: "POST",
        body: payload,
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: platformKnowledgeQueryKeys.all }),
        queryClient.invalidateQueries({ queryKey: knowledgeQueryKeys.all }),
      ])
    },
  })
}

export function usePlatformCreateDocumentFromFileMutation() {
  return useMutation(platformCreateDocumentFromFileMutationOptions(useQueryClient()))
}
