// apps/web/src/features/agents/types.ts

export type ToolPolicyValue = "auto" | "approval"

export type Agent = {
  id: string
  name: string
  slug: string
  description: string | null
  instructions: string
  workspace_id: string
  created_by: string
  tool_names: string[]
  tool_policies: Record<string, ToolPolicyValue> | null
  skill_ids: string[]
  allowed_agent_ids: string[]
  model_provider: string | null
  model: string | null
  model_settings: Record<string, unknown> | null
  azure_deployment: string | null
  max_steps: number | null
  is_active: boolean
  is_favorite: boolean
  last_used_at: string | null
  metadata: Record<string, unknown> | null
  created_at: string
  updated_at: string
  deleted: boolean
  deleted_at: string | null
}

export type AgentsListResponse = {
  agents: Agent[]
  total: number
  limit: number
  offset: number
}

export type AgentCreateRequest = {
  name: string
  slug?: string | null
  description?: string | null
  instructions: string
  tool_names?: string[]
  tool_policies?: Record<string, ToolPolicyValue> | null
  skill_ids?: string[]
  allowed_agent_ids?: string[]
  model_provider?: string | null
  model?: string | null
  model_settings?: Record<string, unknown> | null
  azure_deployment?: string | null
  max_steps?: number | null
  is_active?: boolean
  is_favorite?: boolean
  metadata?: Record<string, unknown> | null
}

export type AgentUpdateRequest = Partial<AgentCreateRequest>
