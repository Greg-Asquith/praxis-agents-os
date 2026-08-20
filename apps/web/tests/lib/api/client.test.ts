import { afterEach, describe, expect, it, vi } from "vitest"

import {
  apiFetch,
  apiRequest,
  apiRequestNoContent,
  buildUrl,
  setApiUnauthorizedHandler,
} from "@/lib/api/client"
import type { ApiError } from "@/lib/api/errors"

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

describe("response contracts", () => {
  it("resolves a no-content request without decoding JSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })))

    await expect(apiRequestNoContent("/agents/agent-1", { method: "DELETE" })).resolves.toBe(
      undefined
    )
  })

  it("parses an API problem from a failed no-content request", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Agent not found." }), {
          headers: { "Content-Type": "application/problem+json" },
          status: 404,
          statusText: "Not Found",
        })
      )
    )

    const request = apiRequestNoContent("/agents/missing", { method: "DELETE" })

    await expect(request).rejects.toMatchObject({
      message: "Agent not found.",
      status: 404,
    } satisfies Partial<ApiError>)
  })

  it("rejects a no-content response requested through the JSON contract", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })))

    await expect(apiRequest<{ id: string }>("/agents/agent-1")).rejects.toThrow(
      "API request to /agents/agent-1 returned status 204 without valid JSON."
    )
  })
})
