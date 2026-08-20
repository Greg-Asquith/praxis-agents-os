import { QueryClient } from "@tanstack/react-query"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { loadOAuthLoginCallback } from "@/features/auth/routes/oauth-login-callback-loader"
import type { AuthResponse } from "@/features/auth/types"
import { getFetchRequest, jsonResponse, stubFetch } from "../../support/fetch-stub"

const completeOauthLogin = vi.fn()
const redirect = vi.fn((path: string): never => {
  throw new RedirectCapture(path)
})
const deps = { completeOauthLogin, redirect }

class RedirectCapture extends Error {
  readonly path: string

  constructor(path: string) {
    super(`Redirected to ${path}`)
    this.path = path
  }
}

const storage = new Map<string, string>()

beforeEach(() => {
  storage.clear()
  completeOauthLogin.mockReset()
  redirect.mockClear()
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
    const result = await loadOAuthLoginCallback(
      {
        queryClient: new QueryClient(),
        search: { state: "state-only" },
      },
      deps
    )

    expect(result).toEqual({
      error: "This sign-in link is missing required information. Please try signing in again.",
      nextPath: null,
      twoFactorPending: false,
    })
    expect(completeOauthLogin).not.toHaveBeenCalled()
  })

  it("rejects a traversal provider from state without exchanging the login callback", async () => {
    const traversalPayload = "eyJwcm92aWRlciI6Ii4uLy4uL2ZpbGVzL2ZpbGUtaWQvcHVyZ2U_eD0ifQ"

    const result = await loadOAuthLoginCallback(
      {
        queryClient: new QueryClient(),
        search: { code: "one-time-code", state: `header.${traversalPayload}.signature` },
      },
      deps
    )

    expect(result).toEqual({
      error: "This sign-in link is missing required information. Please try signing in again.",
      nextPath: null,
      twoFactorPending: false,
    })
    expect(completeOauthLogin).not.toHaveBeenCalled()
  })

  it("rejects a traversal provider from session storage", async () => {
    storage.set("praxis.oauthLoginProvider", "../../files/file-id/purge?x=")

    const result = await loadOAuthLoginCallback(
      {
        queryClient: new QueryClient(),
        search: { code: "one-time-code", state: "one-time-state" },
      },
      deps
    )

    expect(result).toEqual({
      error: "This sign-in link is missing required information. Please try signing in again.",
      nextPath: null,
      twoFactorPending: false,
    })
    expect(completeOauthLogin).not.toHaveBeenCalled()
  })

  it("deduplicates a single-use code across loader reruns", async () => {
    const response: AuthResponse = {
      next_path: "/invitations/accept?token=invite-token",
      requires_twofa: true,
      session: { expires_at: "2026-07-17T00:00:00Z", twofa_verified: false },
      user: null,
    }
    completeOauthLogin.mockResolvedValue(response)
    const queryClient = new QueryClient()
    const search = { code: "one-time-code", state: "one-time-state" }

    storage.set("praxis.oauthLoginProvider", "google")
    const first = await loadOAuthLoginCallback({ queryClient, search }, deps)
    storage.set("praxis.oauthLoginProvider", "google")
    const second = await loadOAuthLoginCallback({ queryClient, search }, deps)

    expect(first).toEqual({
      error: null,
      nextPath: "/invitations/accept?token=invite-token",
      twoFactorPending: true,
    })
    expect(second).toEqual(first)
    expect(completeOauthLogin).toHaveBeenCalledTimes(1)
  })

  it.each([
    ["/invitations/accept?token=invite-token", "/invitations/accept?token=invite-token"],
    ["https://attacker.example", "/"],
  ])("redirects a completed login through the safe return path", async (nextPath, expected) => {
    completeOauthLogin.mockResolvedValue({
      next_path: nextPath,
      requires_twofa: false,
      session: { expires_at: "2026-07-17T00:00:00Z", twofa_verified: true },
      user: null,
    } satisfies AuthResponse)
    storage.set("praxis.oauthLoginProvider", "google")

    await expect(
      loadOAuthLoginCallback(
        {
          queryClient: new QueryClient(),
          search: { code: `code-${nextPath}`, state: `state-${nextPath}` },
        },
        deps
      )
    ).rejects.toMatchObject({ path: expected })

    expect(redirect).toHaveBeenLastCalledWith(expected)
  })

  it("uses the production login API when dependencies are omitted", async () => {
    const response: AuthResponse = {
      next_path: "/agents",
      requires_twofa: true,
      session: { expires_at: "2026-07-17T00:00:00Z", twofa_verified: false },
      user: null,
    }
    const fetchStub = stubFetch(jsonResponse(response))
    storage.set("praxis.oauthLoginProvider", "google")

    await expect(
      loadOAuthLoginCallback({
        queryClient: new QueryClient(),
        search: { code: "production-code", state: "production-state" },
      })
    ).resolves.toEqual({
      error: null,
      nextPath: "/agents",
      twoFactorPending: true,
    })

    const { init, url } = getFetchRequest(fetchStub)
    expect(url.href).toBe("http://localhost:8000/api/v1/auth/oauth/google/callback")
    expect(init).toMatchObject({ credentials: "include", method: "POST" })
  })
})
