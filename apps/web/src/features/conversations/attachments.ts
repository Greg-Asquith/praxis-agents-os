// apps/web/src/features/conversations/attachments.ts

import { confirmFileUpload } from "@/features/files/api/confirm-file-upload"
import { requestFileUpload } from "@/features/files/api/request-file-upload"
import type { WorkspaceFile } from "@/features/files/types"
import { uploadFileDirectly } from "@/lib/api/direct-upload"
import { contentTypeForWorkspaceFile } from "@/lib/file"
import { isRecord, stringValue } from "@/lib/guards"

export const MAX_CHAT_ATTACHMENTS = 5

const CHAT_ATTACHMENT_EXTENSIONS = [
  ".csv",
  ".docx",
  ".html",
  ".jpeg",
  ".jpg",
  ".markdown",
  ".md",
  ".mdx",
  ".pdf",
  ".png",
  ".txt",
  ".webp",
  ".xlsx",
]

export type MessageAttachment = {
  fileId: string
  mediaType: string
  name: string | null
  sizeBytes?: number
}

export function chatAttachmentAcceptValue() {
  return CHAT_ATTACHMENT_EXTENSIONS.join(",")
}

export function isImageAttachmentMediaType(mediaType: string | null | undefined) {
  return mediaType?.split(";")[0]?.trim().toLowerCase().startsWith("image/") ?? false
}

export async function uploadChatAttachment(file: File): Promise<MessageAttachment> {
  const result = await requestFileUpload({
    content_type: contentTypeForWorkspaceFile(file),
    filename: file.name,
    size_bytes: file.size,
  })
  if (result.file) {
    return attachmentFromWorkspaceFile(result.file)
  }
  if (!result.grant) {
    throw new Error("Upload grant was not returned.")
  }

  await uploadFileDirectly(result.grant.upload, file, result.grant.max_size_bytes)
  return attachmentFromWorkspaceFile(
    await confirmFileUpload({ uploadToken: result.grant.upload_token })
  )
}

export function isBinaryUserContentPart(value: unknown): value is {
  identifier: string
  kind: "binary"
  media_type: string
} {
  return (
    isRecord(value) &&
    stringValue(value["kind"]) === "binary" &&
    stringValue(value["identifier"]) !== null &&
    stringValue(value["media_type"]) !== null
  )
}

export function isBinaryUserContentLike(value: unknown) {
  return isRecord(value) && stringValue(value["kind"]) === "binary"
}

export function attachmentFromBinaryUserContentPart(value: unknown): MessageAttachment | null {
  if (!isBinaryUserContentPart(value)) {
    return null
  }

  return {
    fileId: value.identifier,
    mediaType: value.media_type,
    name: null,
  }
}

function attachmentFromWorkspaceFile(file: WorkspaceFile): MessageAttachment {
  return {
    fileId: file.id,
    mediaType: file.content_type,
    name: file.name,
    sizeBytes: file.size_bytes,
  }
}
