// apps/web/src/lib/agent-identity.ts

const AGENT_IDENTITY_COUNT = 8

export function agentIdentityIndex(id: string): number {
  let hash = 0x811c9dc5

  for (let index = 0; index < id.length; index += 1) {
    hash ^= id.charCodeAt(index)
    hash = Math.imul(hash, 0x01000193)
  }

  return (hash >>> 0) % AGENT_IDENTITY_COUNT
}
