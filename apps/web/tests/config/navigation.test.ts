// apps/web/tests/config/navigation.test.ts

import { describe, expect, it } from "vitest"

import { navigationItemsForRole } from "@/config/navigation"

describe("primary navigation", () => {
  it("lists Tools only when the deployment has tools for the user", () => {
    const labels = (hasCustomTools: boolean) =>
      navigationItemsForRole("member", hasCustomTools).map((item) => item.label)

    expect(labels(false)).not.toContain("Tools")
    expect(labels(true)).toContain("Tools")
  })
})
