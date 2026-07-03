// apps/web/src/lib/file.ts

const MIME_TYPE_BY_EXTENSION: Record<string, string> = {
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  md: "text/markdown",
  pdf: "application/pdf",
  txt: "text/plain",
}

export function contentTypeForFile(file: File) {
  if (file.type) {
    return file.type
  }

  const extension = file.name.toLowerCase().split(".").pop()
  return extension
    ? (MIME_TYPE_BY_EXTENSION[extension] ?? "application/octet-stream")
    : "application/octet-stream"
}
