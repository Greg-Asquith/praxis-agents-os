// apps/web/src/features/auth/oauth-callback.ts

import { normalize } from "@/lib/format"
import { decodeBase64Url } from "@/lib/utils"

type OAuthStatePayload = {
  provider?: unknown
}

export type OAuthCallbackSnapshot = {
  code: string | null
  provider: string | null
  providerError: string | null
  state: string | null
}

export type OAuthCallbackInput = {
  provider: string
  code: string
  state: string
}

export type OAuthCallbackSearch = {
  code?: string
  error?: string
  state?: string
}

export function validateOAuthCallbackSearch(search: Record<string, unknown>): OAuthCallbackSearch {
  return {
    ...(typeof search["code"] === "string" ? { code: search["code"] } : {}),
    ...(typeof search["error"] === "string" ? { error: search["error"] } : {}),
    ...(typeof search["state"] === "string" ? { state: search["state"] } : {}),
  }
}

export function readOauthCallback(
  storageKey: string,
  search: OAuthCallbackSearch
): OAuthCallbackSnapshot {
  const state = search.state ?? null
  const storedProvider = normalize(window.sessionStorage.getItem(storageKey))

  return {
    code: search.code ?? null,
    provider: storedProvider ?? providerFromState(state),
    providerError: search.error ?? null,
    state,
  }
}

export function clearOauthCallbackProvider(storageKey: string) {
  window.sessionStorage.removeItem(storageKey)
}

function providerFromState(state: string | null) {
  if (!state) {
    return null
  }

  const payloadSegment = state.split(".")[1]
  if (!payloadSegment) {
    return null
  }

  try {
    const payload = JSON.parse(decodeBase64Url(payloadSegment)) as OAuthStatePayload
    return normalize(typeof payload.provider === "string" ? payload.provider : null)
  } catch {
    return null
  }
}
