// apps/web/src/features/integrations/api/start-oauth.ts

import { useMutation } from "@tanstack/react-query"

import type { IntegrationProvider, OAuthConnectResponse } from "@/features/integrations/types"
import { apiRequest } from "@/lib/api/client"

type StartOAuthInput = {
  provider_key: string
  owner_scope: IntegrationProvider["owner_scope"]
  label: string
  next_path: string
  connection_id?: string
}

async function startOAuth(payload: StartOAuthInput) {
  return apiRequest<OAuthConnectResponse>("/integrations/connections/oauth/start", {
    body: payload,
    method: "POST",
  })
}

export function useStartOAuthMutation() {
  return useMutation({ mutationFn: startOAuth })
}
