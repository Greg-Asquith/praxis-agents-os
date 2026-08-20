// apps/web/src/features/auth/routes/oauth-link-callback-loader.ts

import type { QueryClient } from "@tanstack/react-query"

import { identitiesQueryKey } from "@/features/auth/api/get-identities"
import { completeOauthLink, OAUTH_LINK_PROVIDER_STORAGE_KEY } from "@/features/auth/api/oauth-link"
import {
  clearOauthCallbackProvider,
  readOauthCallback,
  type OAuthCallbackInput,
  type OAuthCallbackSearch,
} from "@/features/auth/oauth-callback"
import type { IdentitiesResponse } from "@/features/auth/types"
import { getErrorMessage } from "@/lib/api/errors"
import { fullDocumentRedirect } from "@/lib/full-document-redirect"

const linkCompletionPromises = new Map<string, Promise<IdentitiesResponse>>()

type OAuthLinkCallbackLoaderDependencies = {
  completeOauthLink?: typeof completeOauthLink
  redirect?: typeof fullDocumentRedirect
}

export async function loadOAuthLinkCallback(
  {
    queryClient,
    search,
  }: {
    queryClient: QueryClient
    search: OAuthCallbackSearch
  },
  deps: OAuthLinkCallbackLoaderDependencies = {}
) {
  const callback = readOauthCallback(OAUTH_LINK_PROVIDER_STORAGE_KEY, search)
  if (callback.providerError) {
    return { error: `The provider reported an error: ${callback.providerError}.` }
  }
  if (!callback.provider || !callback.code || !callback.state) {
    return {
      error: "This sign-in link is missing required information. Please try connecting again.",
    }
  }

  const input = { code: callback.code, provider: callback.provider, state: callback.state }
  clearOauthCallbackProvider(OAUTH_LINK_PROVIDER_STORAGE_KEY)

  let identities: IdentitiesResponse
  try {
    identities = await completeLinkOnce(input, deps.completeOauthLink ?? completeOauthLink)
  } catch (error) {
    return { error: getErrorMessage(error) }
  }

  queryClient.setQueryData(identitiesQueryKey, identities)
  return (deps.redirect ?? fullDocumentRedirect)("/profile")
}

function completeLinkOnce(input: OAuthCallbackInput, complete: typeof completeOauthLink) {
  const key = `${input.provider}:${input.state}:${input.code}`
  const existing = linkCompletionPromises.get(key)
  if (existing) {
    return existing
  }

  const promise = complete(input)
  linkCompletionPromises.set(key, promise)
  return promise
}
