import { describe, expect, it } from "vitest"

import { parseApiError } from "@/lib/api/errors"

function response(contentType: string, body: string, statusText = "Bad Request") {
  return new Response(body, {
    status: 400,
    statusText,
    headers: { "content-type": contentType },
  })
}

describe("parseApiError", () => {
  it.each([
    "application/json",
    "application/problem+json",
    "application/json; charset=utf-8",
    "application/problem+json; charset=utf-8",
  ])("parses problem details from %s", async (contentType) => {
    const error = await parseApiError(
      response(contentType, JSON.stringify({ detail: "No access" }))
    )

    expect(error.message).toBe("No access")
    expect(error.problem).toEqual({ detail: "No access" })
  })

  it("falls back to status text for malformed JSON", async () => {
    const error = await parseApiError(response("application/problem+json", "{"))

    expect(error.message).toBe("Bad Request")
    expect(error.problem).toBeNull()
  })

  it("does not parse non-JSON responses", async () => {
    const error = await parseApiError(response("text/html", '{"detail":"hidden"}'))

    expect(error.message).toBe("Bad Request")
    expect(error.problem).toBeNull()
  })
})
