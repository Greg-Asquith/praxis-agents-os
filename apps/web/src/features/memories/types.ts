// apps/web/src/features/memories/types.ts

export type MemoryScope = "agent" | "user" | "workspace"
export type MemoryType = "fact" | "preference" | "episode" | "outcome"
export type MemoryStatus = "active" | "superseded" | "archived"
// Where a memory came from, as the page's one badge shows it.
export type MemoryOrigin = "learned" | "agent" | "person"
// Private is the viewer's own memories; shared is everything members can see.
export type MemoryAudience = "private" | "shared"
type MemorySource = "interactive" | "scheduled" | "delegated" | "event" | "user" | "dream"

export type Memory = {
  id: string
  scope: MemoryScope
  memory_type: MemoryType
  status: MemoryStatus
  title: string
  content_md: string
  importance: number
  confidence: number
  effective_confidence: number
  agent_id: string | null
  agent_name: string | null
  user_id: string | null
  source: MemorySource
  created_by: "agent" | "user" | "system"
  created_by_user_id: string | null
  expires_at: string | null
  superseded_by_id: string | null
  archived_at: string | null
  archive_reason: string | null
  recall_disabled_at: string | null
  last_edited_by_user_at: string | null
  source_conversation_id: string | null
  source_conversation_title: string | null
  created_at: string
  updated_at: string
}

export type MemoriesListResponse = {
  memories: Memory[]
  audience_counts: Record<MemoryAudience, number>
  total: number
  limit: number
  offset: number
}

export type MemoryDetailResponse = {
  memory: Memory
  chain: Memory[]
}

export type MemoryUpdateRequest = {
  title?: string
  content_md?: string
  importance?: number
  expires_in_days?: number
  recall_disabled?: boolean
}
