// apps/web/tests/features/knowledge/search.test.ts

import { describe, expect, it } from "vitest"
import { validateKnowledgeSearch } from "@/features/knowledge/search"

describe("Knowledge search parameters", () => {
  it.each(["workspace", "platform"])("retains valid %s scope and numeric pages", (scope) => {
    expect(validateKnowledgeSearch({ scope, page: "3" })).toEqual({ scope, page: 3 })
  })
  it.each(["all", "private", "admin", {}, ["platform"], null])(
    "discards invalid scope %j",
    (scope) => {
      expect(validateKnowledgeSearch({ scope })).toEqual({})
    }
  )
  it.each([undefined, "bad", 0, -1, 1, 1.5, Infinity, Number.MAX_SAFE_INTEGER + 1])(
    "discards invalid or default page %s",
    (page) => {
      expect(validateKnowledgeSearch({ page })).toEqual({})
    }
  )
})
