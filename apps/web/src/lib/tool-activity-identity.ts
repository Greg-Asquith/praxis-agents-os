// apps/web/src/lib/tool-activity-identity.ts

export function toolActivityIdentity(
  ownerRunId: string | null | undefined,
  toolCallId: string
): string {
  return JSON.stringify([ownerRunId ?? null, toolCallId])
}

export function approvalActivityIdentity(activity: {
  id: string
  agentRunId?: string | null
  approvalId?: string
}): string {
  return activity.approvalId ?? toolActivityIdentity(activity.agentRunId, activity.id)
}
