// apps/web/src/features/integrations/api/connect-api-key.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { integrationsQueryKeys } from "@/features/integrations/api/query-keys"
import type { IntegrationConnection } from "@/features/integrations/types"
import { apiRequest } from "@/lib/api/client"

type ConnectApiKeyInput = {
  provider_key: string
  label: string
}

async function connectApiKey(payload: ConnectApiKeyInput, apiKey: string) {
  return apiRequest<IntegrationConnection>("/integrations/connections/api-key", {
    body: { ...payload, api_key: apiKey },
    method: "POST",
  })
}

export function useConnectApiKeyMutation(apiKey: string) {
  const queryClient = useQueryClient()

  return useMutation({
    gcTime: 0,
    mutationFn: (payload: ConnectApiKeyInput) => connectApiKey(payload, apiKey),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: integrationsQueryKeys.connections() })
    },
  })
}
