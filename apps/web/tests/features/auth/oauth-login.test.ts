import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { startOauthLogin } from "@/features/auth/api/oauth-login"

const { apiRequest } = vi.hoisted(() => ({ apiRequest: vi.fn() }))

vi.mock("@/lib/api/client", () => ({ apiRequest }))

beforeEach(() => {
  apiRequest.mockReset()
  apiRequest.mockResolvedValue({})
  vi.stubGlobal("window", { location: { origin: "https://praxis.example" } })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("OAuth login start", () => {
  it("sends the invitation return path in OAuth state", async () => {
    await startOauthLogin({
      nextPath: "/invitations/accept?token=invite-token",
      provider: "google",
    })

    expect(apiRequest).toHaveBeenCalledWith("/auth/oauth/google/authorization-url", {
      body: {
        next_path: "/invitations/accept?token=invite-token",
        redirect_uri: "https://praxis.example/oauth/callback",
      },
      method: "POST",
      sessionPolicy: "optional",
    })
  })
})
