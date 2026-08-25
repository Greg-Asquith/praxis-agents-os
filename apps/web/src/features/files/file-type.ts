export type FileVisualType =
  | "audio"
  | "csv"
  | "generic"
  | "html"
  | "image"
  | "json"
  | "markdown"
  | "pdf"
  | "presentation"
  | "spreadsheet"
  | "text"
  | "video"
  | "word"

export type FileTypeSource = {
  category?: string | null
  contentType?: string | null
  extension?: string | null
  name?: string | null
}

const MIME_TYPE_VISUALS: Readonly<Record<string, FileVisualType>> = {
  "application/json": "json",
  "application/msword": "word",
  "application/pdf": "pdf",
  "application/vnd.ms-excel": "spreadsheet",
  "application/vnd.ms-powerpoint": "presentation",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation": "presentation",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "spreadsheet",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "word",
  "text/csv": "csv",
  "text/html": "html",
  "text/markdown": "markdown",
  "text/plain": "text",
}

const EXTENSION_VISUALS: Readonly<Record<string, FileVisualType>> = {
  csv: "csv",
  doc: "word",
  docx: "word",
  htm: "html",
  html: "html",
  json: "json",
  md: "markdown",
  pdf: "pdf",
  ppt: "presentation",
  pptx: "presentation",
  txt: "text",
  xls: "spreadsheet",
  xlsx: "spreadsheet",
}

export function fileVisualType(file: FileTypeSource): FileVisualType {
  const contentType = normalizedContentType(file.contentType)
  const mimeTypeVisual = MIME_TYPE_VISUALS[contentType]
  if (mimeTypeVisual) {
    return mimeTypeVisual
  }

  if (contentType.startsWith("image/")) {
    return "image"
  }
  if (contentType.startsWith("audio/")) {
    return "audio"
  }
  if (contentType.startsWith("video/")) {
    return "video"
  }

  const extension = normalizedExtension(file.extension ?? file.name)
  const extensionVisual = EXTENSION_VISUALS[extension]
  if (extensionVisual) {
    return extensionVisual
  }

  switch (file.category) {
    case "editable_text":
      return "text"
    case "image":
      return "image"
    case "audio":
      return "audio"
    case "video":
      return "video"
    case "html":
      return "html"
    case "ingestible_document":
    case undefined:
    case null:
    default:
      return "generic"
  }
}

function normalizedContentType(contentType: string | null | undefined) {
  return contentType?.split(";")[0]?.trim().toLowerCase() ?? ""
}

function normalizedExtension(value: string | null | undefined) {
  const lastSegment = value?.trim().toLowerCase().split(".").pop() ?? ""
  return lastSegment.replace(/^\./, "")
}
