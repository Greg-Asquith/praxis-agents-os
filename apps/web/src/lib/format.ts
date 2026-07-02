// apps/web/src/lib/format.ts

export function formatDateTime(
  value: string | null | undefined,
  dateStyle: "medium" | "full" | "long" | "short" | undefined = "medium",
  timeStyle: "medium" | "full" | "long" | "short" | undefined = "short"
) {
  if (!value) {
    return "Never"
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: dateStyle,
    timeStyle: timeStyle,
  }).format(new Date(value))
}

export function formatTime(
  value: string | Date,
  hour: "numeric" | "2-digit" | undefined = "numeric",
  minute: "numeric" | "2-digit" | undefined = "2-digit"
) {
  const TIME_FORMATTER = new Intl.DateTimeFormat(undefined, {
    hour: hour,
    minute: minute,
  })
  return TIME_FORMATTER.format(new Date(value))
}

export function pluralize(count: number, singular: string, plural = `${singular}s`) {
  return count === 1 ? singular : plural
}

export function titleCaseToken(value: string, fallback: string) {
  const words = value
    .trim()
    .split(/[\s_-]+/)
    .filter(Boolean)

  if (words.length === 0) {
    return fallback
  }

  return words.map((word) => `${word.slice(0, 1).toUpperCase()}${word.slice(1)}`).join(" ")
}

export function titleFromSegment(segment: string) {
  return segment
    .split("-")
    .filter(Boolean)
    .map((part) => `${part[0]?.toUpperCase() ?? ""}${part.slice(1)}`)
    .join(" ")
}

export function initials(value: string | null | undefined) {
  if (!value) {
    return "PA"
  }
  const parts = value.split(/\s+|@/).filter(Boolean)
  return parts
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("")
}

export function normalize(target: string | null) {
  const normalized = target?.trim().toLowerCase() ?? ""
  return normalized || null
}


export function truncateForPreview(value: string | null, limit: number) {
  if (value === null || value.length <= limit) {
    return value
  }
  return `${value.slice(0, limit)}...`
}