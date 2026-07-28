// apps/web/src/features/artifacts/types.ts

export type ArtifactType = "html" | "markdown" | "mermaid" | "csv" | "image-ref"

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
  workspace_id: string
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

export type ArtifactListResponse = {
  items: ArtifactSummary[]
  total: number
  limit: number
  offset: number
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
