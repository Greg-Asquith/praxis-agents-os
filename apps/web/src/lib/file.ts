// apps/web/src/lib/file.ts

const MIME_TYPE_BY_EXTENSION: Record<string, string> = {
  csv: "text/csv",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  html: "application/html",
  jpeg: "image/jpeg",
  jpg: "image/jpeg",
  json: "application/json",
  markdown: "text/markdown",
  md: "text/markdown",
  mdx: "text/markdown",
  mov: "video/mov",
  mp4: "video/mp4",
  pdf: "application/pdf",
  png: "image/png",
  pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  txt: "text/plain",
  webp: "image/webp",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

export function contentTypeForFile(file: File) {
  if (file.type) {
    return file.type
  }

  return contentTypeForExtension(file.name)
}

export function contentTypeForWorkspaceFile(file: File) {
  const contentType = contentTypeForExtension(file.name)
  return contentType === "application/octet-stream" && file.type ? file.type : contentType
}

export function workspaceFileAcceptValue() {
  return Object.keys(MIME_TYPE_BY_EXTENSION)
    .map((extension) => `.${extension}`)
    .join(",")
}

function contentTypeForExtension(filename: string) {
  const extension = filename.toLowerCase().split(".").pop()
  return extension
    ? (MIME_TYPE_BY_EXTENSION[extension] ?? "application/octet-stream")
    : "application/octet-stream"
}
