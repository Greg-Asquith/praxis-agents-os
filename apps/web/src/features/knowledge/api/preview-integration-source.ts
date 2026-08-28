// apps/web/src/features/knowledge/api/preview-integration-source.ts

import { useMutation } from "@tanstack/react-query"

import type {
  KbIntegrationSourcePreview,
  KbIntegrationSourcePreviewRequest,
} from "@/features/knowledge/types"
import { apiRequest } from "@/lib/api/client"

export function usePreviewIntegrationSourceMutation() {
  return useMutation({
    mutationFn: (payload: KbIntegrationSourcePreviewRequest) =>
      apiRequest<KbIntegrationSourcePreview>("/kb/integration-sources/preview", {
        body: payload,
        method: "POST",
      }),
  })
}
