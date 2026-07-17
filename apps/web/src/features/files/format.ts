// apps/web/src/features/files/format.ts

import type { WorkspaceFile } from "@/features/files/types"

const FILE_TYPE_LABELS: Readonly<Record<string, string>> = {
  "application/json": "JSON",
  "application/pdf": "PDF",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PowerPoint",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Spreadsheet",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word",
  "text/csv": "CSV",
  "text/html": "HTML",
  "text/markdown": "Markdown",
  "text/plain": "Text",
}

export function fileTypeLabel(
  file: Pick<WorkspaceFile, "category" | "content_type" | "extension">
) {
  const contentType = file.content_type.split(";")[0]?.trim().toLowerCase() ?? ""
  const exactLabel = FILE_TYPE_LABELS[contentType]
  if (exactLabel) {
    return exactLabel
  }

  if (file.category === "image" || contentType.startsWith("image/")) {
    return "Image"
  }
  if (file.category === "video" || contentType.startsWith("video/")) {
    return "Video"
  }
  if (file.category === "audio" || contentType.startsWith("audio/")) {
    return "Audio"
  }

  const extension = file.extension.replace(/^\./, "").trim()
  return extension ? extension.toUpperCase() : fileCategoryLabel(file.category)
}

export function fileCategoryLabel(category: string) {
  switch (category) {
    case "editable_text":
      return "Editable text"
    case "ingestible_document":
      return "Document"
    case "image":
      return "Image"
    case "video":
      return "Video"
    case "audio":
      return "Audio"
    default:
      return category.replace(/_/g, " ")
  }
}

export function fileProcessingStatusLabel(status: string) {
  switch (status) {
    case "pending":
      return "Pending"
    case "processing":
      return "Processing"
    case "ready":
      return "Ready"
    case "error":
      return "Error"
    default:
      return status.replace(/_/g, " ")
  }
}

export function fileRevisionKindLabel(kind: string) {
  switch (kind) {
    case "create":
      return "Created"
    case "edit":
      return "Edited"
    case "replace":
      return "Replaced"
    case "restore":
      return "Restored"
    case "import":
      return "Imported"
    default:
      return kind.replace(/_/g, " ")
  }
}
