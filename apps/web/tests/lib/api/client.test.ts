import { describe, expect, it } from "vitest"

import { buildUrl } from "@/lib/api/client"

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
