import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { startOauthLogin } from "@/features/auth/api/oauth-login"
import {
  getFetchRequest,
  getJsonRequestBody,
  jsonResponse,
  stubFetch,
} from "../../support/fetch-stub"

beforeEach(() => {
  vi.stubGlobal("window", { location: { origin: "https://praxis.example" } })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("OAuth login start", () => {
  it("sends the invitation return path in OAuth state", async () => {
    const fetchStub = stubFetch(
      jsonResponse({
        provider: "google",
        authorization_url: "https://accounts.example/authorize",
        state: "state",
        expires_at: "2026-08-20T00:00:00Z",
      })
    )
    await startOauthLogin({
      nextPath: "/invitations/accept?token=invite-token",
      provider: "google",
    })

    const { init, url } = getFetchRequest(fetchStub)
    expect(url.href).toBe("http://localhost:8000/api/v1/auth/oauth/google/authorization-url")
    expect(init).toMatchObject({ credentials: "include", method: "POST" })
    expect(getJsonRequestBody(init)).toEqual({
      next_path: "/invitations/accept?token=invite-token",
      redirect_uri: "https://praxis.example/oauth/callback",
    })
  })
})
