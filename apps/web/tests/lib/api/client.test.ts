import { afterEach, describe, expect, it, vi } from "vitest"

import { apiFetch, buildUrl, setApiUnauthorizedHandler } from "@/lib/api/client"

afterEach(() => {
  setApiUnauthorizedHandler(null)
  vi.unstubAllGlobals()
})

describe("buildUrl", () => {
  it("builds paths within the configured API base", () => {
    expect(buildUrl("/auth/me").toString()).toBe("http://localhost:8000/api/v1/auth/me")
  })

  it("rejects paths that escape the configured API base", () => {
    expect(() => buildUrl("/../../files/file-id/purge?x=/link/callback")).toThrow(
      "API request path escaped the configured API base URL."
    )
  })
})

describe("unauthorized responses", () => {
  it("reports a 401 from an authenticated request, including raw streaming requests", async () => {
    const onUnauthorized = vi.fn()
    setApiUnauthorizedHandler(onUnauthorized)
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 401 })))

    await apiFetch("/conversations/conversation-1/turns", { method: "POST" })

    expect(onUnauthorized).toHaveBeenCalledOnce()
  })

  it("does not report expected pre-auth or partial-session 401 responses", async () => {
    const onUnauthorized = vi.fn()
    setApiUnauthorizedHandler(onUnauthorized)
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 401 })))

    await apiFetch("/auth/login", { method: "POST", sessionPolicy: "optional" })
    await apiFetch("/auth/totp/verify", { method: "POST", sessionPolicy: "optional" })

    expect(onUnauthorized).not.toHaveBeenCalled()
  })
})
