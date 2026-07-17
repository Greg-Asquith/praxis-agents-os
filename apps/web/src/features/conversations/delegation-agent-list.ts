// apps/web/src/features/conversations/delegation-agent-list.ts

import { isRecord } from "@/lib/guards"

export const LIST_DELEGATE_AGENTS_TOOL_NAME = "list_delegate_agents"

export type DelegateAgentSummary = {
  description: string | null
  id: string
  name: string
}

export function delegateAgentSummaries(value: unknown): DelegateAgentSummary[] | null {
  if (!Array.isArray(value)) {
    return null
  }

  const agents: DelegateAgentSummary[] = []
  for (const item of value) {
    if (!isRecord(item) || typeof item["id"] !== "string" || typeof item["name"] !== "string") {
      return null
    }
    agents.push({
      id: item["id"],
      name: item["name"],
      description: typeof item["description"] === "string" ? item["description"] : null,
    })
  }
  return agents
}
