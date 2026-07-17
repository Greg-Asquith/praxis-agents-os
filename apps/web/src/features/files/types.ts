// apps/web/src/features/files/types.ts

import type { AssetUploadGrant, SignedUpload } from "@/features/storage/types"

export type FileContractCategory =
  "editable_text" | "ingestible_document" | "image" | "video" | "audio" | "html"

export type FileProcessingStatus = "pending" | "processing" | "ready" | "error"

export type FileSortField =
  "created_at" | "extension" | "name" | "processing_status" | "size_bytes" | "updated_at"

export type FileSortDirection = "asc" | "desc"

type FileRevisionKind = "create" | "edit" | "replace" | "restore" | "import"

export type WorkspaceFile = {
  id: string
  workspace_id: string
  name: string
  description: string | null
  category: FileContractCategory
  content_type: string
  extension: string
  size_bytes: number
  content_hash: string
  current_revision_id: string
  revision_count: number
  processing_status: FileProcessingStatus
  processing_error: string | null
  created_at: string
  updated_at: string
}

export type FileRevision = {
  id: string
  revision_number: number
  revision_kind: FileRevisionKind
  content_type: string
  size_bytes: number
  content_hash: string
  created_by_user_id: string | null
  created_by_agent_id: string | null
  created_by_system: boolean
  restored_from_revision_id: string | null
  created_at: string
}

export type FileRevisionContent = {
  file_id: string
  revision_id: string
  revision_number: number
  content_type: string
  size_bytes: number
  content_hash: string
  content: string
}

export type FileListResponse = {
  files: WorkspaceFile[]
  total: number
}

export type FileRevisionsListResponse = {
  revisions: FileRevision[]
  total: number
}

export type FileUploadRequest = {
  filename: string
  content_type: string
  size_bytes: number
  content_hash?: string | null
  file_id?: string | null
  allow_duplicate_content?: boolean
}

type FileUploadGrant = AssetUploadGrant & {
  upload: SignedUpload
  over_soft_limit: boolean
  file_id: string
}

export type FileUploadResult = {
  deduplicated: boolean
  file: WorkspaceFile | null
  grant: FileUploadGrant | null
}

export type FileDownloadRequest = {
  revision_id?: string | null
  force_download?: boolean
}

type SignedDownload = {
  ref: {
    bucket: "public" | "private"
    key: string
  }
  url: string
  method: "GET"
  headers: Record<string, string>
  expires_at: string
}

export type FileDownloadGrant = {
  download: SignedDownload
  expires_at: string
}

export type FilePreviewGrant = {
  preview: SignedDownload
  expires_at: string
}
