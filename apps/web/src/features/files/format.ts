// apps/web/src/features/files/format.ts

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

export function shortHash(value: string) {
  return value.length > 12 ? value.slice(0, 12) : value
}

export function relativeDateTime(value: string) {
  const date = new Date(value)
  const diffMs = Date.now() - date.getTime()
  const diffMinutes = Math.round(diffMs / 60_000)

  if (Math.abs(diffMinutes) < 1) {
    return "Just now"
  }
  if (Math.abs(diffMinutes) < 60) {
    return `${String(Math.abs(diffMinutes))}m ${diffMinutes >= 0 ? "ago" : "from now"}`
  }

  const diffHours = Math.round(diffMinutes / 60)
  if (Math.abs(diffHours) < 24) {
    return `${String(Math.abs(diffHours))}h ${diffHours >= 0 ? "ago" : "from now"}`
  }

  const diffDays = Math.round(diffHours / 24)
  if (Math.abs(diffDays) < 14) {
    return `${String(Math.abs(diffDays))}d ${diffDays >= 0 ? "ago" : "from now"}`
  }

  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date)
}
