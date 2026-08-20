// apps/web/src/features/auth/routes/oauth-login-callback-loader.ts

import type { QueryClient } from "@tanstack/react-query"

import { currentUserQueryKey, currentUserQueryOptions } from "@/features/auth/api/get-current-user"
import { completeOauthLogin } from "@/features/auth/api/oauth-login"
import { OAUTH_LOGIN_PROVIDER_STORAGE_KEY } from "@/features/auth/oauth-login-constants"
import {
  clearOauthCallbackProvider,
  readOauthCallback,
  type OAuthCallbackInput,
  type OAuthCallbackSearch,
} from "@/features/auth/oauth-callback"
import type { AuthResponse } from "@/features/auth/types"
import { getErrorMessage } from "@/lib/api/errors"
import { fullDocumentRedirect } from "@/lib/full-document-redirect"
import { safeRedirectPath } from "@/lib/safe-redirect"

const loginCompletionPromises = new Map<string, Promise<AuthResponse>>()

type OAuthLoginCallbackLoaderDependencies = {
  completeOauthLogin?: typeof completeOauthLogin
  redirect?: typeof fullDocumentRedirect
}

export async function loadOAuthLoginCallback(
  {
    queryClient,
    search,
  }: {
    queryClient: QueryClient
    search: OAuthCallbackSearch
  },
  deps: OAuthLoginCallbackLoaderDependencies = {}
) {
  const callback = readOauthCallback(OAUTH_LOGIN_PROVIDER_STORAGE_KEY, search)
  if (callback.providerError) {
    return {
      error: `The provider reported an error: ${callback.providerError}.`,
      nextPath: null,
      twoFactorPending: false,
    }
  }
  if (!callback.provider || !callback.code || !callback.state) {
    return {
      error: "This sign-in link is missing required information. Please try signing in again.",
      nextPath: null,
      twoFactorPending: false,
    }
  }

  const input = { code: callback.code, provider: callback.provider, state: callback.state }
  clearOauthCallbackProvider(OAUTH_LOGIN_PROVIDER_STORAGE_KEY)

  let response: AuthResponse
  try {
    response = await completeLoginOnce(input, deps.completeOauthLogin ?? completeOauthLogin)
  } catch (error) {
    return { error: getErrorMessage(error), nextPath: null, twoFactorPending: false }
  }

  if (response.user) {
    queryClient.setQueryData(currentUserQueryKey, response.user)
  }
  await queryClient.invalidateQueries({ queryKey: currentUserQueryOptions().queryKey })

  const nextPath = safeRedirectPath(response.next_path)
  if (response.requires_twofa) {
    return { error: null, nextPath, twoFactorPending: true }
  }

  return (deps.redirect ?? fullDocumentRedirect)(nextPath ?? "/")
}

function completeLoginOnce(input: OAuthCallbackInput, complete: typeof completeOauthLogin) {
  const key = `${input.provider}:${input.state}:${input.code}`
  const existing = loginCompletionPromises.get(key)
  if (existing) {
    return existing
  }

  const promise = complete(input)
  loginCompletionPromises.set(key, promise)
  return promise
}
