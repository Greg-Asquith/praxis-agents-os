// apps/web/src/features/conversations/types.ts

export type AgentRunStatus =
  "pending" | "running" | "awaiting_approval" | "completed" | "failed" | "cancelled"

type ConversationSource = "direct" | "scheduled" | "delegated"
type AgentRunTrigger = "interactive" | "scheduled" | "delegated"

export type Conversation = {
  id: string
  user_id: string
  workspace_id: string
  created_by: string
  title: string | null
  description: string | null
  status: string
  metadata: Record<string, unknown> | null
  unread: boolean
  source: ConversationSource
  last_message_at: string | null
  active_agent_id: string | null
  agent_slug: string | null
  agent_name: string | null
  active_run_id: string | null
  active_run_status: AgentRunStatus | null
  needs_approval: boolean
  created_at: string
  updated_at: string
}

export type ConversationsListResponse = {
  conversations: Conversation[]
  total: number
  limit: number
  offset: number
}

export type ConversationMessage = {
  id: string
  conversation_id: string
  role: string
  parts: Record<string, unknown>
  metadata: Record<string, unknown> | null
  tool_name: string | null
  error: Record<string, unknown> | null
  sequence: number
  client_message_id: string | null
  created_at: string
  updated_at: string
}

export type ConversationMessagesResponse = {
  messages: ConversationMessage[]
  total: number
  has_more?: boolean
}

export type AgentRun = {
  id: string
  conversation_id: string
  agent_id: string
  workspace_id: string
  user_id: string
  parent_run_id: string | null
  delegation_depth: number
  trigger: AgentRunTrigger
  status: AgentRunStatus
  model_name: string | null
  started_at: string | null
  completed_at: string | null
  failed_at: string | null
  lease_expires_at: string | null
  error_code: string | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export type ConversationActiveRunResponse = {
  active_run: AgentRun | null
}

export type ConversationCreateRequest = {
  agent_id: string
  user_prompt: string
  client_message_id?: string | null
}

export type ConversationTurnCreateRequest = {
  user_prompt: string
  client_message_id?: string | null
}

export type AgentRunResumeDecision = {
  tool_call_id: string
  decision: "approved" | "denied"
  message?: string | null
  override_args?: Record<string, unknown> | null
}

export type AgentRunResumeRequest = {
  decisions: AgentRunResumeDecision[]
}

export type PendingToolApproval = {
  tool_call_id: string
  name: string
  args: unknown
  delegation?: PendingDelegatedApproval | null
}

export type PendingDelegatedApproval = {
  parent_tool_call_id: string
  child_agent_id: string
  child_agent_name: string
  child_conversation_id: string
  child_run_id: string
  pending_approval_count: number
}

export type AgentRunApprovalStateResponse = {
  run_id: string
  conversation_id: string
  approvals: PendingToolApproval[]
  delegations: PendingDelegatedApproval[]
}
