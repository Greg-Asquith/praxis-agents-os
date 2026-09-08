// apps/web/src/components/tool-ui/provider-preview-queries.ts

import { queryOptions, type QueryKey } from "@tanstack/react-query"

import { apiRequest } from "@/lib/api/client"
import { baseIntegrationQueryKeys } from "@/lib/integration-query-keys"

export type ProviderPreview<Meta extends { subject?: string } = { subject?: string }> = {
  kind: string
  content_type: "html" | "text"
  content: string
  meta: Meta
}

export function providerPreviewQueryOptions<
  Meta extends { subject?: string } = { subject?: string },
>({
  conversationId,
  providerKey,
  kind,
  scopeId,
  ref,
  queryKey,
}: {
  conversationId: string | null
  providerKey: string
  kind: string
  scopeId: string
  ref: string
  queryKey?: QueryKey
}) {
  return queryOptions({
    queryKey: queryKey ?? [
      ...baseIntegrationQueryKeys.workspace(),
      "conversation",
      conversationId,
      providerKey,
      kind,
      "content-preview",
      scopeId,
      ref,
    ],
    enabled: conversationId !== null,
    queryFn: () =>
      apiRequest<ProviderPreview<Meta>>(
        `/integrations/conversations/${conversationId ?? "unavailable"}/previews/${kind}`,
        { query: { provider_key: providerKey, ref, scope_id: scopeId } }
      ),
    staleTime: Number.POSITIVE_INFINITY,
    retry: 1,
  })
}
