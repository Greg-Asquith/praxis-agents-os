// apps/web/src/integrations/google_ads/lib/envelopes.ts

import { isRecord } from "@/lib/guards"

export function parseOutcomeEnvelope<Token extends string, Row>(
  value: unknown,
  outcomes: readonly Token[],
  parseSample: (value: unknown, outcome: Token) => Row | null
): { counts: Record<Token, number>; rows: Row[]; truncated: boolean } | null {
  if (
    !isRecord(value) ||
    !isRecord(value["counts"]) ||
    !isRecord(value["samples"]) ||
    typeof value["samples_truncated"] !== "boolean"
  )
    return null
  const counts = {} as Record<Token, number>
  const rows: Row[] = []
  for (const outcome of outcomes) {
    const count = value["counts"][outcome]
    const samples = value["samples"][outcome]
    if (
      typeof count !== "number" ||
      !Number.isSafeInteger(count) ||
      count < 0 ||
      !Array.isArray(samples) ||
      samples.length > count ||
      (!value["samples_truncated"] && samples.length !== count)
    )
      return null
    counts[outcome] = count
    for (const sample of samples) {
      const row = parseSample(sample, outcome)
      if (row === null) return null
      rows.push(row)
    }
  }
  return { counts, rows, truncated: value["samples_truncated"] }
}

export function parseOutcomeList<Row>(
  value: unknown,
  key: string,
  parseRow: (value: unknown) => Row | null,
  identity: (row: Row) => string
): Row[] | null {
  if (!isRecord(value) || !Array.isArray(value[key])) return null
  const rows: Row[] = []
  const identities = new Set<string>()
  for (const item of value[key]) {
    const row = parseRow(item)
    if (row === null) return null
    const id = identity(row)
    if (identities.has(id)) return null
    identities.add(id)
    rows.push(row)
  }
  return rows
}
