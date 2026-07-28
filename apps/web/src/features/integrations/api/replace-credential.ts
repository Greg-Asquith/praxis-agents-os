// apps/web/src/features/integrations/api/replace-credential.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { integrationsQueryKeys } from "@/features/integrations/api/query-keys"
import type { IntegrationConnection } from "@/features/integrations/types"
import { apiRequest } from "@/lib/api/client"

type CredentialReplacementPayload = { api_key: string } | { service_account_json: string }

async function replaceCredential(connectionId: string, payload: CredentialReplacementPayload) {
  return apiRequest<IntegrationConnection>(`/integrations/connections/${connectionId}/credential`, {
    body: payload,
    method: "PUT",
  })
}

export function useReplaceCredentialMutation(
  connectionId: string,
  payload: CredentialReplacementPayload
) {
  const queryClient = useQueryClient()

  return useMutation({
    gcTime: 0,
    mutationFn: () => replaceCredential(connectionId, payload),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: integrationsQueryKeys.connections() }),
        queryClient.invalidateQueries({ queryKey: integrationsQueryKeys.providers() }),
        queryClient.invalidateQueries({ queryKey: integrationsQueryKeys.resources(connectionId) }),
        queryClient.invalidateQueries({ queryKey: integrationsQueryKeys.enabledResources() }),
        queryClient.invalidateQueries({ queryKey: integrationsQueryKeys.activeContexts() }),
      ])
    },
  })
}
