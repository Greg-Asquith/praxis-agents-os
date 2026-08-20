import { QueryClient } from "@tanstack/react-query"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { identitiesQueryKey } from "@/features/auth/api/get-identities"
import { loadOAuthLinkCallback } from "@/features/auth/routes/oauth-link-callback-loader"
import { loadIntegrationOAuthCallback } from "@/features/integrations/routes/oauth-callback-loader"
import type { IdentitiesResponse } from "@/features/auth/types"
import type { OAuthCallbackResponse } from "@/features/integrations/types"
import { getFetchRequest, jsonResponse, stubFetch } from "../../support/fetch-stub"

const completeIntegrationOAuth = vi.fn()
const completeOauthLink = vi.fn()
const redirect = vi.fn((path: string): never => {
  throw new RedirectCapture(path)
})
const integrationDeps = { completeIntegrationOAuth, redirect }
const linkDeps = { completeOauthLink, redirect }

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
  completeIntegrationOAuth.mockReset()
  completeOauthLink.mockReset()
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

describe("secondary OAuth callback loaders", () => {
  it("caches linked identities and performs a full profile reload", async () => {
    const identities: IdentitiesResponse = { has_password: true, identities: [] }
    completeOauthLink.mockResolvedValue(identities)
    storage.set("praxis.oauthLinkProvider", "google")
    const queryClient = new QueryClient()

    const request = loadOAuthLinkCallback(
      { queryClient, search: { code: "link-code", state: "link-state" } },
      linkDeps
    )

    await expect(request).rejects.toMatchObject({ path: "/profile" })
    expect(queryClient.getQueryData(identitiesQueryKey)).toEqual(identities)
  })

  it("rejects a traversal provider from state without exchanging the link callback", async () => {
    const traversalPayload = "eyJwcm92aWRlciI6Ii4uLy4uL2ZpbGVzL2ZpbGUtaWQvcHVyZ2U_eD0ifQ"

    await expect(
      loadOAuthLinkCallback(
        {
          queryClient: new QueryClient(),
          search: { code: "link-code", state: `header.${traversalPayload}.signature` },
        },
        linkDeps
      )
    ).resolves.toEqual({
      error: "This sign-in link is missing required information. Please try connecting again.",
    })
    expect(completeOauthLink).not.toHaveBeenCalled()
  })

  it("rejects a traversal provider from session storage", async () => {
    storage.set("praxis.oauthLinkProvider", "../../files/file-id/purge?x=")

    await expect(
      loadOAuthLinkCallback(
        {
          queryClient: new QueryClient(),
          search: { code: "link-code", state: "link-state" },
        },
        linkDeps
      )
    ).resolves.toEqual({
      error: "This sign-in link is missing required information. Please try connecting again.",
    })
    expect(completeOauthLink).not.toHaveBeenCalled()
  })

  it("returns an integration error without exchanging a callback missing state", async () => {
    await expect(loadIntegrationOAuthCallback({ code: "code" }, integrationDeps)).resolves.toEqual({
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

    const request = loadIntegrationOAuthCallback(
      { code: "code", state: "integration-state" },
      integrationDeps
    )

    await expect(request).rejects.toMatchObject({ path: "/agents" })
  })

  it("returns integration failures to the provider detail page", async () => {
    const payload = "eyJwcm92aWRlcl9rZXkiOiJnb29nbGVfYWRzIn0"
    completeIntegrationOAuth.mockRejectedValue(new Error("Authorization denied"))

    const request = loadIntegrationOAuthCallback(
      { code: "code", state: `header.${payload}.signature` },
      integrationDeps
    )

    await expect(request).rejects.toMatchObject({
      path: "/integrations/google_ads?integration_error=Authorization+denied",
    })
  })

  it("uses the production link API and redirect when dependencies are omitted", async () => {
    const identities: IdentitiesResponse = { has_password: true, identities: [] }
    const fetchStub = stubFetch(jsonResponse(identities))
    storage.set("praxis.oauthLinkProvider", "google")

    const thrownRedirect = await captureRedirect(
      loadOAuthLinkCallback({
        queryClient: new QueryClient(),
        search: { code: "production-link-code", state: "production-link-state" },
      })
    )

    const { init, url } = getFetchRequest(fetchStub)
    expect(url.href).toBe("http://localhost:8000/api/v1/auth/oauth/google/link/callback")
    expect(init).toMatchObject({ credentials: "include", method: "POST" })
    expect(thrownRedirect).toMatchObject({
      options: { href: "https://praxis.example/profile", reloadDocument: true, replace: true },
    })
  })

  it("uses the production integration API and redirect when dependencies are omitted", async () => {
    const response: OAuthCallbackResponse = {
      connection: { id: "connection-production", status: "active" },
      next_path: "/agents",
    }
    const fetchStub = stubFetch(jsonResponse(response))

    const thrownRedirect = await captureRedirect(
      loadIntegrationOAuthCallback({ code: "production-code", state: "production-state" })
    )

    const { init, url } = getFetchRequest(fetchStub)
    expect(url.href).toBe("http://localhost:8000/api/v1/integrations/oauth/callback")
    expect(init).toMatchObject({ credentials: "include", method: "POST" })
    expect(thrownRedirect).toMatchObject({
      options: { href: "https://praxis.example/agents", reloadDocument: true, replace: true },
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
