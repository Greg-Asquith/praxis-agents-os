// apps/web/tests/features/email-suppressions/parse-addresses.test.ts

import { describe, expect, it } from "vitest"

import { parsePastedAddresses } from "@/features/email-suppressions/parse-addresses"

describe("parsePastedAddresses", () => {
  it("reads addresses from names, mailto links, and mixed separators once each", () => {
    expect(
      parsePastedAddresses(
        'Dana Lee <Dana@Example.com>,\nmailto:kai@example.com; "quinn@example.com"\tdana@example.com'
      )
    ).toEqual(["dana@example.com", "kai@example.com", "quinn@example.com"])
  })
})
