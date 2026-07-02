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

export function readOauthCallback(storageKey: string): OAuthCallbackSnapshot {
  const params = new URLSearchParams(window.location.search)
  const state = params.get("state")
  const storedProvider = normalize(window.sessionStorage.getItem(storageKey))

  return {
    code: params.get("code"),
    provider: storedProvider ?? providerFromState(state),
    providerError: params.get("error"),
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
