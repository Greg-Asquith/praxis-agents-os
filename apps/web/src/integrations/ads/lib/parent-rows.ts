// apps/web/src/integrations/ads/lib/parent-rows.ts

/** Change rows under their parent, in the order parents first appear; `live` is those not cancelled. */
export function groupedByParent<T extends { cancelled: boolean }>(
  rows: readonly T[],
  keyOf: (row: T) => string
): { items: T[]; key: string; live: T[] }[] {
  const groups = new Map<string, T[]>()
  for (const row of rows) {
    const key = keyOf(row)
    groups.set(key, [...(groups.get(key) ?? []), row])
  }
  return [...groups].map(([key, items]) => ({
    items,
    key,
    live: items.filter((row) => !row.cancelled),
  }))
}
