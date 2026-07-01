// apps/web/src/lib/format.ts

const TIME_FORMATTER = new Intl.DateTimeFormat(undefined, {
  hour: "numeric",
  minute: "2-digit",
})

export function formatDateTime(value: string | null | undefined) {
  if (!value) {
    return "Never"
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value))
}

export function formatTime(value: string | Date) {
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
