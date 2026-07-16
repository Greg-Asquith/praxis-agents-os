// apps/web/src/features/integrations/api/complete-oauth-callback.ts

import type { OAuthCallbackResponse } from "@/features/integrations/types"
import { apiRequest } from "@/lib/api/client"

export type CompleteIntegrationOAuthInput = {
  state: string
  code: string | null
  error: string | null
}

export async function completeIntegrationOAuth(input: CompleteIntegrationOAuthInput) {
  return apiRequest<OAuthCallbackResponse>("/integrations/oauth/callback", {
    body: input,
    method: "POST",
  })
}
