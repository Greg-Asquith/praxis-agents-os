// apps/web/src/integrations/ads/lib/cancelled-rows.ts

import { isRecord } from "@/lib/guards"

type Entry = { key: string }
type Row = { cancelled: boolean; id: string; targetKey: string }

/** What a card keeps beside its request for Undo: the targets that left it and the cancelled rows. */
export type CancelledChanges<E, R> = { entries: E[]; rows: R[] }

// What differs between the cards that cancel rows inside targets.
export type CancelCard<E, R> = {
  isRow: (value: unknown) => value is R
  parseEntry: (value: unknown) => E | null
  serializeEntries: (entries: readonly E[]) => unknown[]
  // The target with the row back in it; null when it's already there.
  withRow: (entry: E, row: R) => E | null
}

/** Reads the card's own record, which survives a check's redraw. */
export function parseCancelled<E, R>(
  card: CancelCard<E, R>,
  value: unknown
): CancelledChanges<E, R> {
  if (!isRecord(value)) return { entries: [], rows: [] }
  const entries = Array.isArray(value["entries"]) ? value["entries"] : []
  const rows = Array.isArray(value["rows"]) ? value["rows"] : []
  return {
    entries: entries.flatMap((entry) => card.parseEntry(entry) ?? []),
    rows: rows.filter(card.isRow),
  }
}

export function serializeCancelled<E, R>(
  card: CancelCard<E, R>,
  cancelled: CancelledChanges<E, R>
): Record<string, unknown> {
  return { entries: card.serializeEntries(cancelled.entries), rows: cancelled.rows }
}

/** The record after an edit: what the edit took out joins it, and what's back in the request leaves. */
export function retainCancelled<E extends Entry, R extends Row>(
  cancelled: CancelledChanges<E, R>,
  left: { entries: readonly E[]; rows: readonly R[] },
  request: { entries: readonly E[]; rowIds: ReadonlySet<string> }
): CancelledChanges<E, R> {
  const kept = new Set(request.entries.map((entry) => entry.key))
  return {
    entries: [...cancelled.entries, ...left.entries].filter((entry) => !kept.has(entry.key)),
    rows: [...cancelled.rows, ...left.rows].filter((row) => !request.rowIds.has(row.id)),
  }
}

/** Puts a cancelled row back; a target that left the request returns as it left, with the row. */
export function restoreRow<E extends Entry, R extends Row>(
  card: CancelCard<E, R>,
  entries: readonly E[],
  departed: readonly E[],
  row: R
): E[] {
  const held = entries.find((entry) => entry.key === row.targetKey)
  const base = held ?? departed.find((entry) => entry.key === row.targetKey)
  if (!base) return [...entries]
  const next = card.withRow(base, row) ?? base
  return held ? entries.map((entry) => (entry === held ? next : entry)) : [...entries, next]
}

/** Puts back every cancelled row of one target, bringing the target back if it left. */
export function restoreParent<E extends Entry, R extends Row>(
  card: CancelCard<E, R>,
  entries: readonly E[],
  departed: readonly E[],
  rows: readonly R[],
  targetKey: string
): E[] {
  return rows
    .filter((row) => row.cancelled && row.targetKey === targetKey)
    .reduce((current, row) => restoreRow(card, current, departed, row), [...entries])
}
