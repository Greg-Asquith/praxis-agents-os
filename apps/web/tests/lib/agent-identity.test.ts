import { describe, expect, it } from "vitest"

import { agentIdentityColorIndex, agentIdentityIndex } from "@/lib/agent-identity"

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

describe("agentIdentityColorIndex", () => {
  it("maps a stored one-based color to the zero-based palette index", () => {
    expect(agentIdentityColorIndex({ identity_color: 1 })).toBe(0)
    expect(agentIdentityColorIndex({ identity_color: 8 })).toBe(7)
  })

  it("ignores missing or invalid stored colors", () => {
    expect(agentIdentityColorIndex(null)).toBeNull()
    expect(agentIdentityColorIndex(undefined)).toBeNull()
    expect(agentIdentityColorIndex({})).toBeNull()
    expect(agentIdentityColorIndex({ identity_color: 0 })).toBeNull()
    expect(agentIdentityColorIndex({ identity_color: 9 })).toBeNull()
    expect(agentIdentityColorIndex({ identity_color: 2.5 })).toBeNull()
    expect(agentIdentityColorIndex({ identity_color: "3" })).toBeNull()
  })
})
