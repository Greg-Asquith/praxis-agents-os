// apps/web/src/lib/format.ts

export function formatDateTime(value: string | null | undefined) {
  if (!value) {
    return "Never"
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value))
}

export function pluralize(count: number, singular: string, plural = `${singular}s`) {
  return count === 1 ? singular : plural
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
