import { describe, expect, it } from "vitest"

import { agentIdentityIndex } from "@/lib/agent-identity"

describe("agentIdentityIndex", () => {
  it("keeps the FNV-1a palette assignment stable", () => {
    expect(agentIdentityIndex("agent-alpha")).toBe(7)
    expect(agentIdentityIndex("agent-beta")).toBe(3)
    expect(agentIdentityIndex("00000000-0000-0000-0000-000000000001")).toBe(6)
  })

  it("always returns an index in the eight-color palette", () => {
    for (const id of [
      "",
      "agent",
      "agent-with-unicode-🤖",
      "ffffffff-ffff-ffff-ffff-ffffffffffff",
    ]) {
      expect(agentIdentityIndex(id)).toBeGreaterThanOrEqual(0)
      expect(agentIdentityIndex(id)).toBeLessThan(8)
    }
  })
})
