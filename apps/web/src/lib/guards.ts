// apps/web/src/lib/guards.ts

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

export function normalizeRecord(value: unknown): Record<string, unknown> | null {
  if (isRecord(value)) {
    return value
  }
  if (typeof value !== "string") {
    return null
  }
  try {
    const parsed: unknown = JSON.parse(value)
    return isRecord(parsed) ? parsed : null
  } catch {
    return null
  }
}

export function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null
}

export function optionalString(value: unknown): string | null {
  return typeof value === "string" ? value : null
}

export function isOneOf<T extends string>(values: ReadonlySet<T>, value: unknown): value is T {
  const candidates: ReadonlySet<string> = values
  return typeof value === "string" && candidates.has(value)
}

export function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0
}

export function isPositiveInteger(value: unknown): value is number {
  return isNonNegativeInteger(value) && value > 0
}

export function isDateTimeString(value: unknown): value is string {
  return typeof value === "string" && !Number.isNaN(Date.parse(value))
}

export function isNullableString(value: unknown): value is string | null {
  return typeof value === "string" || value === null
}
