// apps/web/src/features/knowledge/types.ts

import type { UntrustedNode } from "@/components/tool-ui/untrusted-node"

export type KbProcessingStatus = "pending" | "processing" | "ready" | "error"
export type KbSourceType = "upload" | "url" | "manual" | "conversation" | "integration"
export type KbContent = string | UntrustedNode

export type KbDocument = {
  id: string
  title: string
  source_type: KbSourceType
  status: KbProcessingStatus
  processing_error: string | null
  processing_attempts: number
  is_private: boolean
  chunk_count: number
  created_by_user_id: string | null
  created_at: string
  updated_at: string
}

export type KbDocumentsListResponse = {
  documents: KbDocument[]
  total: number
  limit: number
  offset: number
}

export type KbDocumentDetail = KbDocument & {
  concept_id: string | null
  source_updated_at: string | null
  summary: string | null
  external_url: string | null
  content_md: KbContent | null
  meta: Record<string, unknown>
}

type KbSearchResult = {
  id: string
  document_id: string
  chunk_index: number
  content: KbContent
  context_line: string | null
  char_start: number
  char_end: number
  meta: Record<string, unknown>
  pending_embedding: boolean
  title: string
  source_type: KbSourceType
  external_url: string | null
  is_private: boolean
  score: number
  sources: string[]
}

export type KbSearchResponse = {
  results: KbSearchResult[]
  mode: "hybrid" | "lexical_fallback"
  query: string
}

export type ListKbDocumentsParams = {
  limit?: number
  offset?: number
  sourceType?: KbSourceType
  status?: KbProcessingStatus
  isPrivate?: boolean
}

export type KbManualDocumentCreateRequest = {
  title: string
  content_md: string
  is_private: boolean
}

export type KbUrlDocumentCreateRequest = {
  url: string
  title: string
  is_private: boolean
}

export type KbFileDocumentCreateRequest = {
  file_id: string
  title?: string
  is_private: boolean
}

export type KbDocumentUpdateRequest = {
  title?: string
  content_md?: string
  is_private?: boolean
}
