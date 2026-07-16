// apps/web/src/features/auth/api/oauth-link.ts

import { useMutation } from "@tanstack/react-query"

import { apiRequest } from "@/lib/api/client"
import type { IdentitiesResponse, OAuthAuthorizationUrlResponse } from "@/features/auth/types"

// Provider name stashed before an OAuth link redirect so the callback route
// knows which provider to complete when the browser returns.
export const OAUTH_LINK_PROVIDER_STORAGE_KEY = "praxis.oauthLinkProvider"

async function startOauthLink(provider: string) {
  return apiRequest<OAuthAuthorizationUrlResponse>(
    `/auth/oauth/${provider}/link/authorization-url`,
    { body: {}, method: "POST" }
  )
}

type CompleteOauthLinkInput = {
  provider: string
  code: string
  state: string
}

export async function completeOauthLink({ provider, code, state }: CompleteOauthLinkInput) {
  return apiRequest<IdentitiesResponse>(`/auth/oauth/${provider}/link/callback`, {
    body: { code, state },
    method: "POST",
  })
}

export function useStartOauthLinkMutation() {
  return useMutation({ mutationFn: startOauthLink })
}
