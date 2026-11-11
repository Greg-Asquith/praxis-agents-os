// apps/web/src/integrations/google_ads/lib/setting-changes.ts

import { isRecord } from "@/lib/guards"

type Entry = Record<string, unknown>

export type UrlParameter = { key: string; value: string }

type UrlOptions = {
  custom_parameters?: UrlParameter[]
  final_url_suffix?: string | null
  tracking_template?: string | null
}

// What differs between the cards that change settings: which ones, and how an entry holds them.
type SettingCard<S extends string, V> = {
  requestedOf: (entry: Entry) => Partial<Record<S, V>>
  settings: readonly S[]
  withSetting: (entry: Entry, setting: S, value: V | undefined) => Entry
}

type SettingChange<S extends string, V> = {
  entry: Entry
  key: string
  requested: Partial<Record<S, V>>
}

type CheckedSettings<S extends string, V> = {
  changes: readonly SettingChange<S, V>[]
  checks: ReadonlyMap<string, { unavailable: boolean }>
}

const URL_OPTIONS: ReadonlySet<string> = new Set([
  "final_url_suffix",
  "tracking_template",
  "custom_parameters",
])

export function isUrlOption(setting: string): boolean {
  return URL_OPTIONS.has(setting)
}

export function parseUrlParameters(value: unknown): UrlParameter[] | null {
  if (!Array.isArray(value)) return null
  const items: UrlParameter[] = []
  for (const item of value) {
    if (!isRecord(item) || typeof item["key"] !== "string" || typeof item["value"] !== "string")
      return null
    items.push({ key: item["key"], value: item["value"] })
  }
  return items
}

export function parametersText(parameters: readonly UrlParameter[]): string {
  return parameters.map((item) => `${item.key}=${item.value}`).join(", ")
}

/** Reads `key=value, key=value`; null when a pair has no key. */
export function parseParametersText(value: string): UrlParameter[] | null {
  const pairs = value
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
  const items: UrlParameter[] = []
  for (const pair of pairs) {
    const split = pair.indexOf("=")
    const key = (split === -1 ? pair : pair.slice(0, split)).trim()
    if (!key) return null
    items.push({ key, value: split === -1 ? "" : pair.slice(split + 1).trim() })
  }
  return items
}

/** The URL options an entry changes, read the way the server reads them. */
export function requestedUrlOptions(entry: Entry): UrlOptions {
  const values: UrlOptions = {}
  const url = isRecord(entry["url_options"]) ? entry["url_options"] : {}
  for (const setting of ["final_url_suffix", "tracking_template"] as const) {
    const value = url[setting]
    if (typeof value === "string") values[setting] = value.trim() || null
  }
  const parameters = parseUrlParameters(url["custom_parameters"])
  if (parameters) values.custom_parameters = parameters
  return values
}

/** Reads the settings a check names, each in card terms; one that doesn't parse is left out. */
export function parseSettingMap<S extends string, V>(
  settings: readonly S[],
  parse: (setting: S, value: unknown) => V | undefined,
  value: unknown
): Partial<Record<S, V>> {
  const values: Partial<Record<S, V>> = {}
  if (!isRecord(value)) return values
  for (const setting of settings) {
    if (!Object.hasOwn(value, setting)) continue
    const parsed = parse(setting, value[setting])
    if (parsed !== undefined) values[setting] = parsed
  }
  return values
}

export function withoutKey(record: Entry, key: string): Entry {
  return Object.fromEntries(Object.entries(record).filter(([name]) => name !== key))
}

/** Writes a setting inside a group of an entry; undefined takes it out, and an empty group goes. */
export function withGroupedSetting(
  entry: Entry,
  group: string,
  setting: string,
  value: unknown
): Entry {
  const current = isRecord(entry[group]) ? entry[group] : {}
  const next = value === undefined ? withoutKey(current, setting) : { ...current, [setting]: value }
  return Object.keys(next).length > 0 ? { ...entry, [group]: next } : withoutKey(entry, group)
}

/** Writes a URL option into an entry; clearing a text option sends an empty string. */
export function withUrlOption(entry: Entry, setting: string, value: unknown): Entry {
  return withGroupedSetting(
    entry,
    "url_options",
    setting,
    value === null && setting !== "custom_parameters" ? "" : value
  )
}

/** The `changes` value with one setting set on the given rows, or cancelled when undefined. */
export function editedSettingChanges<S extends string, V>(
  card: SettingCard<S, V>,
  changes: readonly SettingChange<S, V>[],
  ids: ReadonlySet<string>,
  value: (row: { key: string; setting: S }) => V | undefined
): Entry[] {
  return changes.flatMap((change) => {
    let entry = change.entry
    for (const setting of card.settings) {
      if (change.requested[setting] === undefined || !ids.has(`${change.key}|${setting}`)) continue
      entry = card.withSetting(entry, setting, value({ key: change.key, setting }))
    }
    // An entry must change something, so one with every setting cancelled leaves the request.
    return Object.keys(card.requestedOf(entry)).length > 0 ? [entry] : []
  })
}

/** Puts cancelled settings back, adding their entry again when it had left the request. */
export function restoredSettingChanges<S extends string, V, I extends { key: string }>(
  card: SettingCard<S, V>,
  changes: readonly SettingChange<S, V>[],
  items: readonly (I & { setting: S; value: V })[],
  emptyEntry: (item: I) => Entry
): Entry[] {
  const entries = new Map(changes.map((change) => [change.key, change.entry]))
  for (const item of items) {
    const entry = entries.get(item.key) ?? emptyEntry(item)
    entries.set(item.key, card.withSetting(entry, item.setting, item.value))
  }
  return [...entries.values()]
}

function signature<S extends string, V>(
  settings: readonly S[],
  changes: readonly SettingChange<S, V>[]
): string {
  return JSON.stringify(
    changes.map((change) => [
      change.key,
      // Wrapped so a requested null differs from a setting the entry doesn't name.
      settings.map((setting) => {
        const value = change.requested[setting]
        return value === undefined ? [] : [value]
      }),
    ])
  )
}

/** Whether Google must check again: a check is missing, or the request isn't the one it checked. */
export function settingsNeedCheck<S extends string, V>(
  settings: readonly S[],
  args: CheckedSettings<S, V>,
  checked: CheckedSettings<S, V>
): boolean {
  return (
    [...checked.checks.values()].some((check) => check.unavailable) ||
    signature(settings, args.changes) !== signature(settings, checked.changes)
  )
}

/** The only row of a request with one change, which a card names instead of counting. */
export function soleRow<T>(rows: readonly T[]): T | null {
  return rows.length === 1 ? (rows[0] ?? null) : null
}
