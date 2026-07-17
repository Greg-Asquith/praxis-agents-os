// apps/web/src/lib/format.ts

const COMPACT_TIME_FORMATTER = new Intl.DateTimeFormat(undefined, {
  hour: "numeric",
  minute: "2-digit",
})
const COMPACT_MONTH_DAY_FORMATTER = new Intl.DateTimeFormat(undefined, {
  day: "numeric",
  month: "short",
})
const COMPACT_DATE_FORMATTER = new Intl.DateTimeFormat(undefined, {
  day: "numeric",
  month: "short",
  year: "numeric",
})

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

export function formatCompactDate(
  value: string | null | undefined,
  now: Date = new Date()
): string {
  if (!value) {
    return "Never"
  }

  const date = new Date(value)
  if (
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  ) {
    return COMPACT_TIME_FORMATTER.format(date)
  }

  if (date.getFullYear() === now.getFullYear()) {
    return COMPACT_MONTH_DAY_FORMATTER.format(date)
  }

  return COMPACT_DATE_FORMATTER.format(date)
}

export function formatDateTimeInTimeZone(value: string | null | undefined, timezone: string) {
  if (!value) {
    return "Never"
  }

  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: timezone,
    }).format(new Date(value))
  } catch {
    return formatDateTime(value)
  }
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

export function formatBytes(value: number) {
  if (value >= 1024 * 1024) {
    return `${(value / (1024 * 1024)).toFixed(1)} MB`
  }
  if (value >= 1024) {
    return `${(value / 1024).toFixed(1)} KB`
  }
  return `${String(value)} B`
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

export function normalizeOptionalText(value: string | null | undefined) {
  const normalized = value?.trim() ?? ""
  return normalized || null
}

export function truncateText(value: string, limit: number, suffix = "...") {
  if (value.length <= limit) {
    return value
  }
  return `${value.slice(0, limit)}${suffix}`
}
