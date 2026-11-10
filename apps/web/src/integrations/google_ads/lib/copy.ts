// apps/web/src/integrations/google_ads/lib/copy.ts

export function approvalCountLine(count: number, noun: string): string {
  return `${String(count)} ${noun}${count === 1 ? "" : "s"}`
}
