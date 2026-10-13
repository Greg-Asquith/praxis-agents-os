// apps/web/src/features/conversations/attachments.ts

import type { WorkspaceFile } from "@/features/files/types"
import { uploadWorkspaceFile } from "@/lib/api/workspace-file-upload"
import { WORKSPACE_FILE_MIME_TYPES } from "@/lib/file"
import { isRecord, stringValue } from "@/lib/guards"

export const MAX_CHAT_ATTACHMENTS = 5

export type MessageAttachment = {
  scope?: "platform"
  fileId: string
  mediaType: string
  name: string | null
  sizeBytes?: number
}

export function chatAttachmentAcceptValue(videoToolsAvailable: boolean) {
  return Object.entries(WORKSPACE_FILE_MIME_TYPES)
    .filter(([, contentType]) => videoToolsAvailable || !contentType.startsWith("video/"))
    .map(([extension]) => `.${extension}`)
    .join(",")
}

// Drag and drop bypasses the picker's accept list, so both paths check here.
export function chatAttachmentRefusal(file: File, videoToolsAvailable: boolean) {
  const extension = file.name.toLowerCase().split(".").pop() ?? ""
  const contentType = Object.hasOwn(WORKSPACE_FILE_MIME_TYPES, extension)
    ? WORKSPACE_FILE_MIME_TYPES[extension]
    : undefined
  if (contentType === undefined) {
    const kinds = videoToolsAvailable ? "images, videos, or text files" : "images, or text files"
    return `${file.name} can't be attached. Attach documents, spreadsheets, presentations, ${kinds}.`
  }
  if (contentType.startsWith("video/") && !videoToolsAvailable) {
    return "Video can't be attached to messages yet. Upload it to Files instead."
  }
  return null
}

function hasMediaTypeFamily(mediaType: string | null | undefined, family: "image" | "video") {
  return mediaType?.split(";")[0]?.trim().toLowerCase().startsWith(`${family}/`) ?? false
}

export function isImageAttachmentMediaType(mediaType: string | null | undefined) {
  return hasMediaTypeFamily(mediaType, "image")
}

export function isVideoAttachmentMediaType(mediaType: string | null | undefined) {
  return hasMediaTypeFamily(mediaType, "video")
}

export async function uploadChatAttachment(
  file: File,
  onProgress: (fraction: number) => void
): Promise<MessageAttachment> {
  return attachmentFromWorkspaceFile(await uploadWorkspaceFile(file, onProgress))
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

export function attachmentFromWorkspaceFile(file: WorkspaceFile): MessageAttachment {
  return {
    ...(file.scope === "platform" ? { scope: "platform" as const } : {}),
    fileId: file.id,
    mediaType: file.content_type,
    name: file.name,
    sizeBytes: file.size_bytes,
  }
}
