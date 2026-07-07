// apps/web/src/features/conversations/message-parts/types.ts

import type { MessageAttachment } from "@/features/conversations/attachments"

export type ParsedMessageRole = "user" | "assistant" | "tool" | "system" | "unknown"
export type ParsedAttachment = MessageAttachment

type ToolActivityKind = "call" | "result" | "approval" | "retry" | "unknown"

export type ToolActivityStatus =
  "running" | "awaiting_approval" | "completed" | "failed" | "denied" | "unknown"

export type ToolApprovalDecision = "approved" | "denied"

export type DelegationToolActivity = {
  status: "running" | "awaiting_approval" | "completed" | "failed" | "unknown"
  agentId: string | null
  agentName: string | null
  taskPreview: string | null
  output: string | null
  error: string | null
  runId: string | null
  conversationId: string | null
  pendingApprovalCount: number
  truncated: boolean
}

export type ToolActivity = {
  id: string
  kind: ToolActivityKind
  status: ToolActivityStatus
  name: string
  args?: unknown
  decision?: ToolApprovalDecision
  delegate?: DelegationToolActivity
  result?: unknown
  outcome?: string | null
  toolKind?: string
}

type UnsupportedMessagePart = {
  id: string
  label: string
  preview: string
}

export type ParsedConversationMessage = {
  id: string
  role: ParsedMessageRole
  sequence: number
  agentRunId: string | null
  clientMessageId: string | null
  createdAt: string
  text: string[]
  thinking: string[]
  attachments: MessageAttachment[]
  toolActivities: ToolActivity[]
  unsupportedParts: UnsupportedMessagePart[]
}

export type PendingUserMessage = {
  clientMessageId: string
  conversationId: string | null
  text: string
  attachments?: MessageAttachment[]
  createdAt: string
}
