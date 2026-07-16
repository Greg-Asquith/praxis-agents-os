import { describe, expect, it } from "vitest"

import { fullDocumentRedirect } from "@/lib/full-document-redirect"

describe("full document redirect", () => {
  it("throws a replace-style document navigation for loader handling", () => {
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: { location: { origin: "https://praxis.example" } },
    })

    try {
      const redirect = fullDocumentRedirect as (path: string) => unknown
      redirect("/profile")
      expect.unreachable("Expected TanStack Router to throw a redirect")
    } catch (error) {
      expect(error).toBeInstanceOf(Response)
      expect(error).toMatchObject({
        options: {
          href: "https://praxis.example/profile",
          reloadDocument: true,
          replace: true,
        },
      })
    } finally {
      Reflect.deleteProperty(globalThis, "window")
    }
  })
})
