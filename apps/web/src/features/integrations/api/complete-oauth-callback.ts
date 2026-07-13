// apps/web/src/features/integrations/api/complete-oauth-callback.ts

import { useMutation } from "@tanstack/react-query"

import type { OAuthCallbackResponse } from "@/features/integrations/types"
import { apiRequest } from "@/lib/api/client"

export type CompleteIntegrationOAuthInput = {
  state: string
  code: string | null
  error: string | null
}

async function completeIntegrationOAuth(input: CompleteIntegrationOAuthInput) {
  return apiRequest<OAuthCallbackResponse>("/integrations/oauth/callback", {
    body: input,
    method: "POST",
  })
}

export function useCompleteIntegrationOAuthMutation() {
  return useMutation({ mutationFn: completeIntegrationOAuth })
}
