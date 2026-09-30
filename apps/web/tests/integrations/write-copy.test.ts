// apps/web/tests/integrations/write-copy.test.ts

import { describe, expect, it } from "vitest"

import { titleCaseWords } from "@/integrations/write-copy"

describe("integration write copy", () => {
  it("title-cases objects while keeping advertising acronyms", () => {
    expect(titleCaseWords("campaign shared list")).toBe("Campaign Shared List")
    expect(titleCaseWords("target cpa bids")).toBe("Target CPA Bids")
    expect(titleCaseWords("final urls")).toBe("Final URLs")
  })
})
