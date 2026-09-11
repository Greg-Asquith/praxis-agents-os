// apps/web/src/features/artifacts/types.ts

export type ArtifactType = "html" | "markdown" | "mermaid" | "csv" | "image-ref"
export type ArtifactScope = "workspace" | "platform"
export type ArtifactScopeFilter = "all" | ArtifactScope
export type ArtifactSortDirection = "asc" | "desc"
export type ArtifactSortField = "artifact_type" | "title" | "updated_at" | "version_count"

export type ArtifactViewGrant = {
  url: string
  expires_at: string
}

export type ArtifactVersion = {
  id: string
  created_at: string
  created_by_user_id: string | null
  created_by_agent_id: string | null
  created_by_system: boolean
  size_bytes: number
  revision_number: number
  revision_kind: "create" | "edit" | "restore"
  restored_from_revision_id: string | null
}

export type ArtifactSummary = {
  id: string
  scope: ArtifactScope
  workspace_id: string | null
  is_published: boolean
  can_manage_platform: boolean
  can_edit: boolean
  agent_id: string | null
  conversation_id: string | null
  run_id: string | null
  current_version_id: string
  artifact_type: ArtifactType
  title: string
  created_at: string
  updated_at: string
  version_count: number
}

export type Artifact = Omit<ArtifactSummary, "version_count"> & {
  versions: ArtifactVersion[]
}

// Management reads carry the published pointer; null means never published.
export type PlatformArtifactSummary = ArtifactSummary & { published_version_id: string | null }
export type PlatformArtifact = Artifact & { published_version_id: string | null }

export type ArtifactListResponse = {
  items: ArtifactSummary[]
  total: number
  limit: number
  offset: number
}

export type PlatformArtifactListResponse = Omit<ArtifactListResponse, "items"> & {
  items: PlatformArtifactSummary[]
}

export type ArtifactContent = {
  content: string | null
  content_type: string
  size_bytes: number
  download_url: string | null
}

type ArtifactShare = {
  id: string
  token_prefix: string
  expires_at: string
  version_id: string
  created_at: string
  created_by_user_id: string | null
  creator_display: string | null
  revoked_at: string | null
  revoked_by_user_id: string | null
  last_accessed_at: string | null
  access_count: number
}

export type ArtifactShareListResponse = {
  items: ArtifactShare[]
}

export type ArtifactShareCreated = {
  id: string
  share_url: string
  token_prefix: string
  expires_at: string
  version_id: string
}
