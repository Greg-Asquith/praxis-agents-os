// apps/web/src/integrations/ads/lib/cell-text.ts

/** A table cell's value as text; empty when the row holds something else there. */
export function cellText(value: unknown): string {
  return typeof value === "string" ? value : ""
}
