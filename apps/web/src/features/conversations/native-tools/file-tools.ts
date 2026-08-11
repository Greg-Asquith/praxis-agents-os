// apps/web/src/features/conversations/native-tools/file-tools.ts

import type { FileContractCategory, FileProcessingStatus } from "@/features/files/types"
import { isRecord } from "@/lib/guards"

export const WRITE_FILE_TOOL_NAME = "write_file"
export const READ_FILE_TOOL_NAME = "read_file"
export const LIST_FILES_TOOL_NAME = "list_files"
export const IMAGE_TOOL_NAME = "generate_image"

export type WriteFileToolResult = {
  name: string
  bytes_written: number
  file_id: string
  revision_id: string
}

export type GenerateImageToolResult = {
  file_id: string
  height: number
  media_type: string
  name: string
  revision_id: string
  size_bytes: number
  width: number
}

export type ReadFileUrlToolResult = {
  category?: FileContractCategory
  expires_at: string
  file_id: string
  media_type?: string
  mode: "url"
  name: string
  processing_status?: FileProcessingStatus
  revision_id?: string
  url: string
}

export type ReadFileContentToolResult = {
  category?: FileContractCategory
  content: string
  end_offset: number
  expires_at?: string | null
  file_id?: string
  kind?: string
  media_type?: string
  mode: "content"
  name?: string
  offset: number
  processing_status?: FileProcessingStatus
  revision_id?: string
  source?: string
  total_bytes: number
  truncated: boolean
  hint?: string
}

export type ReadFileStatusToolResult = {
  category?: FileContractCategory
  file_id: string
  kind?: string
  media_type?: string
  message: string
  name: string
  processing_status?: FileProcessingStatus
  revision_id?: string
  source?: string
  status: string
}

export type ReadFileImageToolResult = {
  category?: FileContractCategory
  file_id: string
  kind?: string
  media_type?: string
  name: string
  processing_status?: FileProcessingStatus
  revision_id?: string
  source: "image"
}

export type RuntimeFileSummary = {
  category: FileContractCategory
  id: string
  media_type: string
  name: string
  processing_status: FileProcessingStatus
  size_bytes: number
  updated_at: string
}

export type ListFilesToolResult = {
  files: RuntimeFileSummary[]
  total: number
}

export type FileEntitySnapshot = {
  category?: FileContractCategory
  contentType?: string
  fileId: string
  name: string
  processingStatus?: FileProcessingStatus
  sizeBytes?: number
  updatedAt?: string
}

export function writeFileResult(value: unknown): WriteFileToolResult | null {
  if (!isRecord(value)) {
    return null
  }
  if (
    typeof value["name"] !== "string" ||
    typeof value["bytes_written"] !== "number" ||
    typeof value["file_id"] !== "string" ||
    typeof value["revision_id"] !== "string"
  ) {
    return null
  }

  return {
    name: value["name"],
    bytes_written: value["bytes_written"],
    file_id: value["file_id"],
    revision_id: value["revision_id"],
  }
}

export function generateImageResult(value: unknown): GenerateImageToolResult | null {
  if (!isRecord(value)) {
    return null
  }
  if (
    typeof value["file_id"] !== "string" ||
    typeof value["height"] !== "number" ||
    typeof value["media_type"] !== "string" ||
    typeof value["name"] !== "string" ||
    typeof value["revision_id"] !== "string" ||
    typeof value["size_bytes"] !== "number" ||
    typeof value["width"] !== "number"
  ) {
    return null
  }
  return {
    file_id: value["file_id"],
    height: value["height"],
    media_type: value["media_type"],
    name: value["name"],
    revision_id: value["revision_id"],
    size_bytes: value["size_bytes"],
    width: value["width"],
  }
}

export function listFilesResult(value: unknown): ListFilesToolResult | null {
  if (!isRecord(value)) {
    return null
  }
  if (!Array.isArray(value["files"])) {
    return null
  }
  if (typeof value["total"] !== "number") {
    return null
  }

  const files = value["files"].map(runtimeFileSummary).filter((file) => file !== null)
  if (files.length !== value["files"].length) {
    return null
  }

  return { files, total: value["total"] }
}

export function readFileUrlResult(value: unknown): ReadFileUrlToolResult | null {
  const result = unwrapToolReturnValue(value)
  if (!isRecord(result)) {
    return null
  }
  if (
    result["mode"] !== "url" ||
    typeof result["file_id"] !== "string" ||
    typeof result["name"] !== "string" ||
    typeof result["url"] !== "string" ||
    typeof result["expires_at"] !== "string"
  ) {
    return null
  }

  return {
    expires_at: result["expires_at"],
    file_id: result["file_id"],
    mode: "url",
    name: result["name"],
    url: result["url"],
    ...(isFileContractCategory(result["category"]) ? { category: result["category"] } : {}),
    ...(typeof result["media_type"] === "string" ? { media_type: result["media_type"] } : {}),
    ...(isFileProcessingStatus(result["processing_status"])
      ? { processing_status: result["processing_status"] }
      : {}),
    ...(typeof result["revision_id"] === "string" ? { revision_id: result["revision_id"] } : {}),
  }
}

export function readFileContentResult(value: unknown): ReadFileContentToolResult | null {
  const result = unwrapToolReturnValue(value)
  if (!isRecord(result)) {
    return null
  }
  if (
    result["mode"] !== "content" ||
    typeof result["content"] !== "string" ||
    typeof result["offset"] !== "number" ||
    typeof result["end_offset"] !== "number" ||
    typeof result["total_bytes"] !== "number" ||
    typeof result["truncated"] !== "boolean"
  ) {
    return null
  }

  return {
    mode: "content",
    content: result["content"],
    offset: result["offset"],
    end_offset: result["end_offset"],
    total_bytes: result["total_bytes"],
    truncated: result["truncated"],
    ...(isFileContractCategory(result["category"]) ? { category: result["category"] } : {}),
    ...(typeof result["expires_at"] === "string" ? { expires_at: result["expires_at"] } : {}),
    ...(typeof result["file_id"] === "string" ? { file_id: result["file_id"] } : {}),
    ...(typeof result["hint"] === "string" ? { hint: result["hint"] } : {}),
    ...(typeof result["kind"] === "string" ? { kind: result["kind"] } : {}),
    ...(typeof result["media_type"] === "string" ? { media_type: result["media_type"] } : {}),
    ...(typeof result["name"] === "string" ? { name: result["name"] } : {}),
    ...(isFileProcessingStatus(result["processing_status"])
      ? { processing_status: result["processing_status"] }
      : {}),
    ...(typeof result["revision_id"] === "string" ? { revision_id: result["revision_id"] } : {}),
    ...(typeof result["source"] === "string" ? { source: result["source"] } : {}),
  }
}

export function readFileStatusResult(value: unknown): ReadFileStatusToolResult | null {
  const result = unwrapToolReturnValue(value)
  if (!isRecord(result)) {
    return null
  }
  if (
    typeof result["file_id"] !== "string" ||
    typeof result["name"] !== "string" ||
    typeof result["message"] !== "string" ||
    typeof result["status"] !== "string"
  ) {
    return null
  }

  return {
    file_id: result["file_id"],
    message: result["message"],
    name: result["name"],
    status: result["status"],
    ...(isFileContractCategory(result["category"]) ? { category: result["category"] } : {}),
    ...(typeof result["kind"] === "string" ? { kind: result["kind"] } : {}),
    ...(typeof result["media_type"] === "string" ? { media_type: result["media_type"] } : {}),
    ...(isFileProcessingStatus(result["processing_status"])
      ? { processing_status: result["processing_status"] }
      : {}),
    ...(typeof result["revision_id"] === "string" ? { revision_id: result["revision_id"] } : {}),
    ...(typeof result["source"] === "string" ? { source: result["source"] } : {}),
  }
}

export function readFileImageResult(value: unknown): ReadFileImageToolResult | null {
  const result = unwrapToolReturnValue(value)
  if (!isRecord(result)) {
    return null
  }
  if (
    result["source"] !== "image" ||
    typeof result["file_id"] !== "string" ||
    typeof result["name"] !== "string"
  ) {
    return null
  }

  return {
    file_id: result["file_id"],
    name: result["name"],
    source: "image",
    ...(isFileContractCategory(result["category"]) ? { category: result["category"] } : {}),
    ...(typeof result["kind"] === "string" ? { kind: result["kind"] } : {}),
    ...(typeof result["media_type"] === "string" ? { media_type: result["media_type"] } : {}),
    ...(isFileProcessingStatus(result["processing_status"])
      ? { processing_status: result["processing_status"] }
      : {}),
    ...(typeof result["revision_id"] === "string" ? { revision_id: result["revision_id"] } : {}),
  }
}

export function fileEntityFromWriteResult(result: WriteFileToolResult): FileEntitySnapshot {
  return {
    fileId: result.file_id,
    name: result.name,
    sizeBytes: result.bytes_written,
  }
}

export function fileEntityFromGeneratedImage(result: GenerateImageToolResult): FileEntitySnapshot {
  return {
    category: "image",
    contentType: result.media_type,
    fileId: result.file_id,
    name: result.name,
    processingStatus: "ready",
    sizeBytes: result.size_bytes,
  }
}

export function fileEntityFromReadUrlResult(result: ReadFileUrlToolResult): FileEntitySnapshot {
  return {
    ...(result.category ? { category: result.category } : {}),
    ...(result.media_type ? { contentType: result.media_type } : {}),
    fileId: result.file_id,
    name: result.name,
    ...(result.processing_status ? { processingStatus: result.processing_status } : {}),
  }
}

export function fileEntityFromRuntimeFile(result: RuntimeFileSummary): FileEntitySnapshot {
  return {
    category: result.category,
    contentType: result.media_type,
    fileId: result.id,
    name: result.name,
    processingStatus: result.processing_status,
    sizeBytes: result.size_bytes,
    updatedAt: result.updated_at,
  }
}

export function fileEntityFromReadContentResult(
  result: ReadFileContentToolResult
): FileEntitySnapshot | null {
  if (!result.file_id || !result.name) {
    return null
  }
  return {
    ...(result.category ? { category: result.category } : {}),
    ...(result.media_type ? { contentType: result.media_type } : {}),
    fileId: result.file_id,
    name: result.name,
  }
}

export function fileEntityFromReadStatusResult(
  result: ReadFileStatusToolResult
): FileEntitySnapshot {
  return {
    ...(result.category ? { category: result.category } : {}),
    ...(result.media_type ? { contentType: result.media_type } : {}),
    fileId: result.file_id,
    name: result.name,
  }
}

export function fileEntityFromReadImageResult(result: ReadFileImageToolResult): FileEntitySnapshot {
  return {
    ...(result.category ? { category: result.category } : {}),
    ...(result.media_type ? { contentType: result.media_type } : {}),
    fileId: result.file_id,
    name: result.name,
  }
}

function runtimeFileSummary(value: unknown): RuntimeFileSummary | null {
  if (!isRecord(value)) {
    return null
  }
  if (
    typeof value["id"] !== "string" ||
    typeof value["name"] !== "string" ||
    !isFileContractCategory(value["category"]) ||
    typeof value["media_type"] !== "string" ||
    typeof value["size_bytes"] !== "number" ||
    !isFileProcessingStatus(value["processing_status"]) ||
    typeof value["updated_at"] !== "string"
  ) {
    return null
  }
  return {
    id: value["id"],
    name: value["name"],
    category: value["category"],
    media_type: value["media_type"],
    size_bytes: value["size_bytes"],
    processing_status: value["processing_status"],
    updated_at: value["updated_at"],
  }
}

function isFileContractCategory(value: unknown): value is FileContractCategory {
  return (
    value === "editable_text" ||
    value === "ingestible_document" ||
    value === "image" ||
    value === "video" ||
    value === "audio"
  )
}

function isFileProcessingStatus(value: unknown): value is FileProcessingStatus {
  return value === "pending" || value === "processing" || value === "ready" || value === "error"
}

function unwrapToolReturnValue(value: unknown): unknown {
  let unwrapped = value
  if (isRecord(value)) {
    const returnValue = value["return_value"]
    if (isRecord(returnValue) || Array.isArray(returnValue)) {
      unwrapped = returnValue
    }
  }
  if (Array.isArray(unwrapped)) {
    return unwrapped.find((item) => isRecord(item)) ?? unwrapped
  }
  return unwrapped
}
