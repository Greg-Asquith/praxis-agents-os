// apps/web/src/features/integrations/api/connect-service-account.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { integrationsQueryKeys } from "@/features/integrations/api/query-keys"
import type { IntegrationConnection } from "@/features/integrations/types"
import { apiRequest } from "@/lib/api/client"

type ConnectServiceAccountInput = {
  provider_key: string
  label: string
}

async function connectServiceAccount(payload: ConnectServiceAccountInput, credentialsJson: string) {
  return apiRequest<IntegrationConnection>("/integrations/connections/service-account", {
    body: { ...payload, service_account_json: credentialsJson },
    method: "POST",
  })
}

export function useConnectServiceAccountMutation(credentialsJson: string) {
  const queryClient = useQueryClient()

  return useMutation({
    gcTime: 0,
    mutationFn: (payload: ConnectServiceAccountInput) =>
      connectServiceAccount(payload, credentialsJson),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: integrationsQueryKeys.connections() })
    },
  })
}
