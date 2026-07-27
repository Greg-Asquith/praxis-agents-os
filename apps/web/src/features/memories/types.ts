// apps/web/src/features/memories/types.ts

export type MemoryScope = "agent" | "user" | "workspace"
export type MemoryKind = "core" | "note"
export type MemoryType = "fact" | "preference" | "episode" | "outcome"
export type MemoryStatus = "active" | "superseded" | "archived"
type MemorySource = "interactive" | "scheduled" | "delegated" | "event" | "user"

export type Memory = {
  id: string
  scope: MemoryScope
  kind: MemoryKind
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
  created_by: "agent" | "user"
  created_by_user_id: string | null
  expires_at: string | null
  superseded_by_id: string | null
  archived_at: string | null
  archive_reason: string | null
  created_at: string
  updated_at: string
}

export type MemoriesListResponse = {
  memories: Memory[]
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
}
