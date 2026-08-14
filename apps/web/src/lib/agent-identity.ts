// apps/web/src/lib/agent-identity.ts

export const AGENT_IDENTITY_COUNT = 8

export function agentIdentityColorIndex(
  metadata: Record<string, unknown> | null | undefined
): number | null {
  const value = metadata?.["identity_color"]
  if (typeof value !== "number" || !Number.isInteger(value)) {
    return null
  }
  if (value < 1 || value > AGENT_IDENTITY_COUNT) {
    return null
  }
  return value - 1
}

export function agentIdentityIndex(id: string): number {
  let hash = 0x811c9dc5

  for (let index = 0; index < id.length; index += 1) {
    hash ^= id.charCodeAt(index)
    hash = Math.imul(hash, 0x01000193)
  }

  return (hash >>> 0) % AGENT_IDENTITY_COUNT
}
