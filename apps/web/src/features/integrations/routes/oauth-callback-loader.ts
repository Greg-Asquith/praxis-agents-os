// apps/web/src/features/integrations/routes/oauth-callback-loader.ts

import {
  completeIntegrationOAuth,
  type CompleteIntegrationOAuthInput,
} from "@/features/integrations/api/complete-oauth-callback"
import type { OAuthCallbackResponse } from "@/features/integrations/types"
import type { OAuthCallbackSearch } from "@/features/auth/oauth-callback"
import { getErrorMessage } from "@/lib/api/errors"
import { fullDocumentRedirect } from "@/lib/full-document-redirect"
import { isRecord } from "@/lib/guards"
import { decodeBase64Url } from "@/lib/utils"

const completionPromises = new Map<string, Promise<OAuthCallbackResponse>>()

type IntegrationOAuthCallbackLoaderDependencies = {
  completeIntegrationOAuth?: typeof completeIntegrationOAuth
  redirect?: typeof fullDocumentRedirect
}

export async function loadIntegrationOAuthCallback(
  search: OAuthCallbackSearch,
  deps: IntegrationOAuthCallbackLoaderDependencies = {}
) {
  if (!search.state) {
    return { error: "This connection link is missing its OAuth state." }
  }

  const input = {
    code: search.code ?? null,
    error: search.error ?? null,
    state: search.state,
  }

  let response: OAuthCallbackResponse
  try {
    response = await completeOnce(input, deps.completeIntegrationOAuth ?? completeIntegrationOAuth)
  } catch (error) {
    const message = getErrorMessage(error)
    const providerKey = providerKeyFromState(search.state)
    if (providerKey) {
      const query = new URLSearchParams({ integration_error: message })
      return (deps.redirect ?? fullDocumentRedirect)(
        `/integrations/${encodeURIComponent(providerKey)}?${query.toString()}`
      )
    }
    return { error: message }
  }

  return (deps.redirect ?? fullDocumentRedirect)(response.next_path ?? "/")
}

function providerKeyFromState(state: string) {
  const payloadSegment = state.split(".")[1]
  if (!payloadSegment) {
    return null
  }
  try {
    const payload: unknown = JSON.parse(decodeBase64Url(payloadSegment))
    if (!isRecord(payload)) {
      return null
    }
    const providerKey = typeof payload["provider_key"] === "string" ? payload["provider_key"] : null
    return providerKey && /^[a-z0-9_]+$/.test(providerKey) ? providerKey : null
  } catch {
    return null
  }
}

function completeOnce(
  input: CompleteIntegrationOAuthInput,
  complete: typeof completeIntegrationOAuth
) {
  const key = `${input.state}:${input.code ?? ""}:${input.error ?? ""}`
  const existing = completionPromises.get(key)
  if (existing) {
    return existing
  }

  const promise = complete(input)
  completionPromises.set(key, promise)
  return promise
}
