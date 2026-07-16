import { QueryClient } from "@tanstack/react-query"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { identitiesQueryKey } from "@/features/auth/api/get-identities"
import { loadOAuthLinkCallback } from "@/features/auth/routes/oauth-link-callback-loader"
import { loadIntegrationOAuthCallback } from "@/features/integrations/routes/oauth-callback-loader"
import type { IdentitiesResponse } from "@/features/auth/types"
import type { OAuthCallbackResponse } from "@/features/integrations/types"

const { completeIntegrationOAuth, completeOauthLink } = vi.hoisted(() => ({
  completeIntegrationOAuth: vi.fn(),
  completeOauthLink: vi.fn(),
}))

vi.mock("@/features/auth/api/oauth-link", () => ({
  completeOauthLink,
  OAUTH_LINK_PROVIDER_STORAGE_KEY: "praxis.oauthLinkProvider",
}))
vi.mock("@/features/integrations/api/complete-oauth-callback", () => ({
  completeIntegrationOAuth,
}))

const storage = new Map<string, string>()

beforeEach(() => {
  storage.clear()
  completeIntegrationOAuth.mockReset()
  completeOauthLink.mockReset()
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

describe("secondary OAuth callback loaders", () => {
  it("caches linked identities and performs a full profile reload", async () => {
    const identities: IdentitiesResponse = { has_password: true, identities: [] }
    completeOauthLink.mockResolvedValue(identities)
    storage.set("praxis.oauthLinkProvider", "google")
    const queryClient = new QueryClient()

    const redirect = await captureRedirect(
      loadOAuthLinkCallback({
        queryClient,
        search: { code: "link-code", state: "link-state" },
      })
    )

    expect(queryClient.getQueryData(identitiesQueryKey)).toEqual(identities)
    expect(redirect).toMatchObject({
      options: {
        href: "https://praxis.example/profile",
        reloadDocument: true,
        replace: true,
      },
    })
  })

  it("returns an integration error without exchanging a callback missing state", async () => {
    await expect(loadIntegrationOAuthCallback({ code: "code" })).resolves.toEqual({
      error: "This connection link is missing its OAuth state.",
    })
    expect(completeIntegrationOAuth).not.toHaveBeenCalled()
  })

  it("uses the integration response path for a full document reload", async () => {
    const response: OAuthCallbackResponse = {
      connection: { id: "connection-1", status: "active" },
      next_path: "/agents",
    }
    completeIntegrationOAuth.mockResolvedValue(response)

    const redirect = await captureRedirect(
      loadIntegrationOAuthCallback({ code: "code", state: "integration-state" })
    )

    expect(redirect).toMatchObject({
      options: {
        href: "https://praxis.example/agents",
        reloadDocument: true,
        replace: true,
      },
    })
  })
})

async function captureRedirect(promise: Promise<unknown>) {
  try {
    await promise
  } catch (error) {
    expect(error).toBeInstanceOf(Response)
    return error
  }
  throw new Error("Expected the loader to throw a redirect.")
}
