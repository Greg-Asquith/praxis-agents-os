// apps/web/src/features/auth/api/oauth-login.ts

import { useMutation } from "@tanstack/react-query"

import { OAUTH_LOGIN_CALLBACK_PATH } from "@/features/auth/oauth-login-constants"
import type { AuthResponse, OAuthAuthorizationUrlResponse } from "@/features/auth/types"
import { apiRequest } from "@/lib/api/client"

export { OAUTH_LOGIN_PROVIDER_STORAGE_KEY } from "@/features/auth/oauth-login-constants"

type OAuthRedirectPayload = {
  redirect_uri?: string
  next_path?: string
}

type StartOauthLoginInput = {
  provider: string
  nextPath: string | null
}

type CompleteOauthLoginInput = {
  provider: string
  code: string
  state: string
}

function oauthLoginRedirectUri() {
  return `${window.location.origin}${OAUTH_LOGIN_CALLBACK_PATH}`
}

function oauthRedirectPayload(nextPath?: string | null): OAuthRedirectPayload {
  return {
    redirect_uri: oauthLoginRedirectUri(),
    ...(nextPath ? { next_path: nextPath } : {}),
  }
}

export async function startOauthLogin({ provider, nextPath }: StartOauthLoginInput) {
  return apiRequest<OAuthAuthorizationUrlResponse>(
    `/auth/oauth/${encodeURIComponent(provider)}/authorization-url`,
    {
      body: oauthRedirectPayload(nextPath),
      method: "POST",
      sessionPolicy: "optional",
    }
  )
}

export async function completeOauthLogin({ provider, code, state }: CompleteOauthLoginInput) {
  return apiRequest<AuthResponse>(`/auth/oauth/${encodeURIComponent(provider)}/callback`, {
    body: { ...oauthRedirectPayload(), code, state },
    method: "POST",
    sessionPolicy: "optional",
  })
}

export function useStartOauthLoginMutation() {
  return useMutation({ mutationFn: startOauthLogin })
}
