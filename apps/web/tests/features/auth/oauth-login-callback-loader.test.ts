import { QueryClient } from "@tanstack/react-query"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { loadOAuthLoginCallback } from "@/features/auth/routes/oauth-login-callback-loader"
import type { AuthResponse } from "@/features/auth/types"

const { completeOauthLogin } = vi.hoisted(() => ({
  completeOauthLogin: vi.fn(),
}))

vi.mock("@/features/auth/api/oauth-login", () => ({ completeOauthLogin }))

const storage = new Map<string, string>()

beforeEach(() => {
  storage.clear()
  completeOauthLogin.mockReset()
  vi.stubGlobal("window", {
    location: { origin: "https://praxis.example" },
    sessionStorage: {
      getItem: (key: string) => storage.get(key) ?? null,
      removeItem: (key: string) => storage.delete(key),
      setItem: (key: string, value: string) => storage.set(key, value),
    },
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("OAuth login callback loader", () => {
  it("returns a renderable error without exchanging an incomplete callback", async () => {
    const result = await loadOAuthLoginCallback({
      queryClient: new QueryClient(),
      search: { state: "state-only" },
    })

    expect(result).toEqual({
      error: "This sign-in link is missing required information. Please try signing in again.",
      twoFactorPending: false,
    })
    expect(completeOauthLogin).not.toHaveBeenCalled()
  })

  it("deduplicates a single-use code across loader reruns", async () => {
    const response: AuthResponse = {
      requires_twofa: true,
      session: { expires_at: "2026-07-17T00:00:00Z", twofa_verified: false },
      user: null,
    }
    completeOauthLogin.mockResolvedValue(response)
    const queryClient = new QueryClient()
    const search = { code: "one-time-code", state: "one-time-state" }

    storage.set("praxis.oauthLoginProvider", "google")
    const first = await loadOAuthLoginCallback({ queryClient, search })
    storage.set("praxis.oauthLoginProvider", "google")
    const second = await loadOAuthLoginCallback({ queryClient, search })

    expect(first).toEqual({ error: null, twoFactorPending: true })
    expect(second).toEqual(first)
    expect(completeOauthLogin).toHaveBeenCalledTimes(1)
  })
})
