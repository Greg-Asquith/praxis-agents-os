// apps/web/src/features/skills/types.ts

type SkillDocumentStatus = "ready" | "failed"

type SkillDocumentManifestEntry = {
  original: string
  markdown: string | null
  filename: string
  content_type: string
  size_bytes: number
  markdown_size_bytes: number | null
  status: SkillDocumentStatus
  error: string | null
  updated_at: string
}

export type SkillDocument = SkillDocumentManifestEntry & {
  name: string
}

export type Skill = {
  id: string
  name: string
  human_name: string | null
  description: string
  instructions: string
  workspace_id: string
  created_by: string
  documentation_refs: Record<string, SkillDocumentManifestEntry>
  is_active: boolean
  is_favorite: boolean
  last_used_at: string | null
  metadata: Record<string, unknown> | null
  created_at: string
  updated_at: string
  deleted: boolean
  deleted_at: string | null
}

export type SkillsListResponse = {
  skills: Skill[]
  total: number
  limit: number
  offset: number
}

export type SkillCreateRequest = {
  name: string
  human_name?: string | null
  description: string
  instructions: string
  is_active?: boolean
  is_favorite?: boolean
  metadata?: Record<string, unknown> | null
}

export type SkillUpdateRequest = Partial<SkillCreateRequest>

export type SkillDocumentUploadRequest = {
  document_name: string
  filename: string
  content_type: string
  size_bytes: number
}

export type SkillDocumentsListResponse = {
  documents: SkillDocument[]
  total: number
}

export type SkillDocumentMarkdownResponse = {
  content: string
  name: string
  truncated: boolean
}

export type SignedDownload = {
  ref: {
    bucket: "public" | "private"
    key: string
  }
  url: string
  method: "GET"
  headers: Record<string, string>
  expires_at: string
}
