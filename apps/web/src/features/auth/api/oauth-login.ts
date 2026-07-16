// apps/web/src/features/auth/api/oauth-login.ts

import { useMutation } from "@tanstack/react-query"

import { OAUTH_LOGIN_CALLBACK_PATH } from "@/features/auth/oauth-login-constants"
import type { AuthResponse, OAuthAuthorizationUrlResponse } from "@/features/auth/types"
import { apiRequest } from "@/lib/api/client"

export { OAUTH_LOGIN_PROVIDER_STORAGE_KEY } from "@/features/auth/oauth-login-constants"

type OAuthRedirectPayload = {
  redirect_uri?: string
}

type CompleteOauthLoginInput = {
  provider: string
  code: string
  state: string
}

function oauthLoginRedirectUri() {
  return `${window.location.origin}${OAUTH_LOGIN_CALLBACK_PATH}`
}

function oauthRedirectPayload(): OAuthRedirectPayload {
  return { redirect_uri: oauthLoginRedirectUri() }
}

async function startOauthLogin(provider: string) {
  return apiRequest<OAuthAuthorizationUrlResponse>(`/auth/oauth/${provider}/authorization-url`, {
    body: oauthRedirectPayload(),
    method: "POST",
  })
}

export async function completeOauthLogin({ provider, code, state }: CompleteOauthLoginInput) {
  return apiRequest<AuthResponse>(`/auth/oauth/${provider}/callback`, {
    body: { ...oauthRedirectPayload(), code, state },
    method: "POST",
  })
}

export function useStartOauthLoginMutation() {
  return useMutation({ mutationFn: startOauthLogin })
}
