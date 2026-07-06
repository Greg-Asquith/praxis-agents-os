// apps/web/src/features/conversations/file-tools.ts

import { normalizeToolArgs } from "@/features/conversations/message-parts"
import type { FileCardFile } from "@/features/files/components/file-card"
import { isRecord } from "@/lib/guards"

export const WRITE_FILE_TOOL_NAME = "write_file"
export const PROMOTE_SCRATCH_TOOL_NAME = "promote_scratch"
export const READ_FILE_TOOL_NAME = "read_file"
export const LIST_FILES_TOOL_NAME = "list_files"

export type WriteFileToolResult = {
  destination: "scratch" | "file"
  name: string
  bytes_written: number
  expires_at?: string | null
  file_id?: string | null
  revision_id?: string | null
}

export type PromoteScratchToolResult = {
  deleted_scratch: boolean
  file_id: string
  name: string
  revision_id: string
}

export type ReadFileUrlToolResult = {
  expires_at: string
  file_id: string
  mode: "url"
  name: string
  url: string
}

export type ReadFileContentToolResult = {
  category?: string
  content: string
  end_offset: number
  expires_at?: string | null
  file_id?: string
  kind?: string
  media_type?: string
  mode: "content"
  name?: string
  offset: number
  processing_status?: string
  revision_id?: string
  source?: string
  total_bytes: number
  truncated: boolean
  hint?: string
}

export type ReadFileStatusToolResult = {
  category?: string
  file_id: string
  kind?: string
  media_type?: string
  message: string
  name: string
  processing_status?: string
  revision_id?: string
  source?: string
  status: string
}

export type ReadFileImageToolResult = {
  category?: string
  file_id: string
  kind?: string
  media_type?: string
  name: string
  processing_status?: string
  revision_id?: string
  source: "image"
}

export type RuntimeFileSummary = {
  category: string
  id: string
  media_type: string
  name: string
  processing_status: string
  size_bytes: number
  updated_at: string
}

type RuntimeScratchSummary = {
  content_bytes: number
  expires_at: string
  name: string
  updated_at: string
}

export type ListFilesToolResult = {
  files: RuntimeFileSummary[]
  scratch: RuntimeScratchSummary[]
  total: number
}

export function writeFileResult(value: unknown): WriteFileToolResult | null {
  if (!isRecord(value)) {
    return null
  }
  if (value["destination"] !== "scratch" && value["destination"] !== "file") {
    return null
  }
  if (typeof value["name"] !== "string" || typeof value["bytes_written"] !== "number") {
    return null
  }

  return {
    destination: value["destination"],
    name: value["name"],
    bytes_written: value["bytes_written"],
    expires_at: typeof value["expires_at"] === "string" ? value["expires_at"] : null,
    file_id: typeof value["file_id"] === "string" ? value["file_id"] : null,
    revision_id: typeof value["revision_id"] === "string" ? value["revision_id"] : null,
  }
}

export function writeFileContentArg(args: unknown): string | null {
  const record = normalizeToolArgs(args)
  if (!isRecord(record) || typeof record["content"] !== "string") {
    return null
  }
  return record["content"].trim() ? record["content"] : null
}

export function promoteScratchResult(value: unknown): PromoteScratchToolResult | null {
  if (!isRecord(value)) {
    return null
  }
  if (
    typeof value["file_id"] !== "string" ||
    typeof value["revision_id"] !== "string" ||
    typeof value["name"] !== "string" ||
    typeof value["deleted_scratch"] !== "boolean"
  ) {
    return null
  }

  return {
    deleted_scratch: value["deleted_scratch"],
    file_id: value["file_id"],
    name: value["name"],
    revision_id: value["revision_id"],
  }
}

export function listFilesResult(value: unknown): ListFilesToolResult | null {
  if (!isRecord(value)) {
    return null
  }
  if (!Array.isArray(value["files"]) || !Array.isArray(value["scratch"])) {
    return null
  }
  if (typeof value["total"] !== "number") {
    return null
  }

  const files = value["files"].map(runtimeFileSummary).filter((file) => file !== null)
  const scratch = value["scratch"].map(runtimeScratchSummary).filter((entry) => entry !== null)
  if (files.length !== value["files"].length || scratch.length !== value["scratch"].length) {
    return null
  }

  return { files, scratch, total: value["total"] }
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
    ...(typeof result["category"] === "string" ? { category: result["category"] } : {}),
    ...(typeof result["expires_at"] === "string" ? { expires_at: result["expires_at"] } : {}),
    ...(typeof result["file_id"] === "string" ? { file_id: result["file_id"] } : {}),
    ...(typeof result["hint"] === "string" ? { hint: result["hint"] } : {}),
    ...(typeof result["kind"] === "string" ? { kind: result["kind"] } : {}),
    ...(typeof result["media_type"] === "string" ? { media_type: result["media_type"] } : {}),
    ...(typeof result["name"] === "string" ? { name: result["name"] } : {}),
    ...(typeof result["processing_status"] === "string"
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
    ...(typeof result["category"] === "string" ? { category: result["category"] } : {}),
    ...(typeof result["kind"] === "string" ? { kind: result["kind"] } : {}),
    ...(typeof result["media_type"] === "string" ? { media_type: result["media_type"] } : {}),
    ...(typeof result["processing_status"] === "string"
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
    ...(typeof result["category"] === "string" ? { category: result["category"] } : {}),
    ...(typeof result["kind"] === "string" ? { kind: result["kind"] } : {}),
    ...(typeof result["media_type"] === "string" ? { media_type: result["media_type"] } : {}),
    ...(typeof result["processing_status"] === "string"
      ? { processing_status: result["processing_status"] }
      : {}),
    ...(typeof result["revision_id"] === "string" ? { revision_id: result["revision_id"] } : {}),
  }
}

export function fileCardFromWriteResult(result: WriteFileToolResult): FileCardFile | null {
  if (result.destination !== "file" || !result.file_id) {
    return null
  }
  return {
    fileId: result.file_id,
    name: result.name,
    sizeBytes: result.bytes_written,
  }
}

export function fileCardFromPromoteResult(result: PromoteScratchToolResult): FileCardFile {
  return {
    fileId: result.file_id,
    name: result.name,
  }
}

export function fileCardFromReadUrlResult(result: ReadFileUrlToolResult): FileCardFile {
  return {
    fileId: result.file_id,
    name: result.name,
  }
}

export function fileCardFromRuntimeFile(result: RuntimeFileSummary): FileCardFile {
  return {
    category: result.category,
    contentType: result.media_type,
    fileId: result.id,
    name: result.name,
    sizeBytes: result.size_bytes,
  }
}

export function fileCardFromReadContentResult(
  result: ReadFileContentToolResult
): FileCardFile | null {
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

export function fileCardFromReadStatusResult(result: ReadFileStatusToolResult): FileCardFile {
  return {
    ...(result.category ? { category: result.category } : {}),
    ...(result.media_type ? { contentType: result.media_type } : {}),
    fileId: result.file_id,
    name: result.name,
  }
}

export function fileCardFromReadImageResult(result: ReadFileImageToolResult): FileCardFile {
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
    typeof value["category"] !== "string" ||
    typeof value["media_type"] !== "string" ||
    typeof value["size_bytes"] !== "number" ||
    typeof value["processing_status"] !== "string" ||
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

function runtimeScratchSummary(value: unknown): RuntimeScratchSummary | null {
  if (!isRecord(value)) {
    return null
  }
  if (
    typeof value["name"] !== "string" ||
    typeof value["content_bytes"] !== "number" ||
    typeof value["updated_at"] !== "string" ||
    typeof value["expires_at"] !== "string"
  ) {
    return null
  }
  return {
    name: value["name"],
    content_bytes: value["content_bytes"],
    updated_at: value["updated_at"],
    expires_at: value["expires_at"],
  }
}

function unwrapToolReturnValue(value: unknown): unknown {
  if (!isRecord(value)) {
    return value
  }
  return isRecord(value["return_value"]) ? value["return_value"] : value
}
