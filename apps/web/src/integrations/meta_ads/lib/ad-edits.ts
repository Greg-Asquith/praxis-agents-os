// apps/web/src/integrations/meta_ads/lib/ad-edits.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import { formatLocalTime, isLocalTime } from "@/integrations/meta_ads/lib/budget-schedule"
import { isNonEmptyString, isOneOf, isRecord, isStringArray } from "@/lib/guards"

export type AdSettingKey = "name" | "start_at" | "end_at"

// In the order the card and the tool list them.
const SETTINGS: readonly { key: AdSettingKey; title: string }[] = [
  { key: "name", title: "Name" },
  { key: "start_at", title: "Start Time" },
  { key: "end_at", title: "End Time" },
]
const SETTING_KEYS: ReadonlySet<AdSettingKey> = new Set(SETTINGS.map((setting) => setting.key))

type AdCheck = {
  timeZone: string | null
  // Each setting now; null means not set.
  before: Partial<Record<AdSettingKey, string | null>>
  // The values the problems were found for.
  requested: Partial<Record<AdSettingKey, string | null>>
  problems: string[]
  // The ad set's own start and end; the ad's times must fall inside them.
  adSetSchedule: { start: string | null; end: string | null } | null
  unavailable: boolean
}

/** One setting's new value; "none" means the ad follows its ad set's schedule. */
export type AdSettingEdit = { key: AdSettingKey; value: string }

export type AdEdit = {
  id: string
  accountId: string
  name: string
  settings: AdSettingEdit[]
  check: AdCheck | null
  // The entry as sent, so edits keep the reference the card doesn't change.
  raw: Record<string, unknown>
}

export type AdEditArgs = { edits: AdEdit[] }

/** One proposed ad, kept when the operator drops it so it can come back. */
export type AdEditRow = { edit: AdEdit; included: boolean }

export function adSettingTitle(key: AdSettingKey): string {
  return SETTINGS.find((setting) => setting.key === key)?.title ?? key
}

export function parseAdEditArgs(value: unknown): AdEditArgs | null {
  if (!isRecord(value) || !Array.isArray(value["changes"])) return null
  const checks = isRecord(value["_checks"]) ? value["_checks"] : {}
  const edits: AdEdit[] = []
  for (const item of value["changes"]) {
    if (!isRecord(item) || !isRecord(item["ad"])) return null
    const reference = item["ad"]
    const id = reference["ad_id"]
    if (!isNonEmptyString(id)) return null
    edits.push({
      id,
      accountId: typeof reference["account_id"] === "string" ? reference["account_id"] : "",
      name: isNonEmptyString(reference["label"]) ? reference["label"] : id,
      settings: SETTINGS.flatMap(({ key }) =>
        typeof item[key] === "string" ? [{ key, value: item[key] }] : []
      ),
      check: parseCheck(checks[id]),
      raw: item,
    })
  }
  return { edits }
}

function parseCheck(value: unknown): AdCheck | null {
  if (!isRecord(value)) return null
  return {
    timeZone: isNonEmptyString(value["time_zone"]) ? value["time_zone"] : null,
    before: settingValues(value["before"]),
    requested: settingValues(value["requested"]),
    problems: isStringArray(value["problems"]) ? value["problems"] : [],
    adSetSchedule: parseSchedule(value["ad_set_schedule"]),
    unavailable: value["unavailable"] === true,
  }
}

function parseSchedule(value: unknown): AdCheck["adSetSchedule"] {
  if (!isRecord(value)) return null
  const time = (key: string) => (isNonEmptyString(value[key]) ? value[key] : null)
  return { start: time("start_at"), end: time("end_at") }
}

/** The ad set's schedule on one line, such as "Sun 1 Nov 2026, 00:00 → No end date". */
export function adSetScheduleText(edit: AdEdit): string | null {
  const schedule = edit.check?.adSetSchedule
  if (!schedule) return null
  const start = schedule.start ? formatLocalTime(schedule.start) : "When turned on"
  const end = schedule.end ? formatLocalTime(schedule.end) : "No end date"
  return `${start} → ${end}`
}

/** The account time zone the card's times are in, when the server named one. */
export function adEditTimeZone(args: AdEditArgs): string | null {
  return args.edits.find((edit) => edit.check?.timeZone)?.check?.timeZone ?? null
}

function settingValues(value: unknown): Partial<Record<AdSettingKey, string | null>> {
  if (!isRecord(value)) return {}
  const values: Partial<Record<AdSettingKey, string | null>> = {}
  for (const [key, item] of Object.entries(value))
    if (isOneOf(SETTING_KEYS, key) && (item === null || typeof item === "string"))
      values[key] = item
  return values
}

/** True when the server's problems were found for exactly the values now on the card. */
function checkIsCurrent(edit: AdEdit): boolean {
  const check = edit.check
  if (check === null) return false
  return (
    Object.keys(check.requested).length === edit.settings.length &&
    edit.settings.every(
      (setting) =>
        setting.key in check.requested &&
        check.requested[setting.key] === (setting.value === "none" ? null : setting.value)
    )
  )
}

export function currentAdProblems(edit: AdEdit): string[] {
  return checkIsCurrent(edit) ? (edit.check?.problems ?? []) : []
}

/** A note under the ad when its values haven't been checked. */
export function adNote(edit: AdEdit): string | null {
  const check = edit.check
  if (check === null || check.unavailable)
    return "This ad couldn't be checked before approval. Meta checks it when you approve."
  if (!checkIsCurrent(edit))
    return "You changed these values, so Meta checks them again when you approve."
  return null
}

export function formatAdSetting(key: AdSettingKey, value: string | null): string {
  if (key === "name") return value ?? "Not set"
  return value === null || value === "none" ? "Follows the ad set" : formatLocalTime(value)
}

/** Why one value on the card can't be sent, or null. */
export function adSettingProblem(setting: AdSettingEdit): string | null {
  if (setting.key === "name") return setting.value.trim() === "" ? "Enter a name." : null
  return setting.value === "none" || isLocalTime(setting.value) ? null : "Choose a date and time."
}

/** Why the proposed changes can't be approved yet, or null. */
export function adEditProblem(args: AdEditArgs | null): string | null {
  if (args === null) return null
  if (args.edits.length === 0) return "Keep at least one ad, or decline this request."
  if (args.edits.some((edit) => edit.settings.some((setting) => adSettingProblem(setting))))
    return "Correct the highlighted values before approving."
  if (args.edits.some((edit) => currentAdProblems(edit).length > 0))
    return "Change the ads Meta won't accept or switch them off, or decline this request."
  return null
}

/** The new values on one line, for the ad's closed row. */
export function adEditSummary(edit: AdEdit): string {
  return edit.settings
    .map(
      (setting) => `${adSettingTitle(setting.key)}: ${formatAdSetting(setting.key, setting.value)}`
    )
    .join(" · ")
}

/** The proposed ads with the ones the operator dropped, in the proposed order. */
export function adEditRows(proposed: AdEditArgs, current: AdEditArgs): AdEditRow[] {
  const kept = new Map(current.edits.map((edit) => [edit.id, edit]))
  return proposed.edits.map((edit) => {
    const edited = kept.get(edit.id)
    return { edit: edited ?? edit, included: edited !== undefined }
  })
}

/** The `changes` argument after setting one value, or including or dropping an ad. */
export function editAds(
  rows: readonly AdEditRow[],
  id: string,
  change: { included: boolean } | AdSettingEdit
): Record<string, unknown>[] {
  return rows.flatMap((row) => {
    const same = row.edit.id === id
    const included = same && "included" in change ? change.included : row.included
    if (!included) return []
    if (!same || !("key" in change)) return [row.edit.raw]
    return [{ ...row.edit.raw, [change.key]: change.value }]
  })
}

export function adEditDetails(args: AdEditArgs | null): FanOutDetail[] {
  if (args === null) return []
  return [{ label: "Ads", value: String(args.edits.length) }]
}

// Result models

type EditOutcomeToken = "updated" | "already_set" | "failed" | "unverified"
const OUTCOMES: ReadonlySet<EditOutcomeToken> = new Set([
  "updated",
  "already_set",
  "failed",
  "unverified",
])

type AdSettingResult = {
  key: AdSettingKey
  before: string | null
  requested: string | null
  after: string | null
}

type AdEditOutcome = {
  id: string
  name: string
  changes: AdSettingResult[]
  outcome: EditOutcomeToken
  errorCode: string | null
  message: string | null
}

export type AdEditResult = { accountId: string; timeZone: string; ads: AdEditOutcome[] }

export function parseAdEditResult(value: unknown): AdEditResult | null {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value["account_id"]) ||
    !isNonEmptyString(value["time_zone"]) ||
    !Array.isArray(value["ads"])
  )
    return null
  const ads: AdEditOutcome[] = []
  for (const item of value["ads"]) {
    const row = parseOutcome(item)
    if (row === null) return null
    ads.push(row)
  }
  return { accountId: value["account_id"], timeZone: value["time_zone"], ads }
}

function parseOutcome(value: unknown): AdEditOutcome | null {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value["ad_id"]) ||
    !isOneOf(OUTCOMES, value["outcome"]) ||
    !Array.isArray(value["changes"])
  )
    return null
  const changes: AdSettingResult[] = []
  for (const item of value["changes"]) {
    if (!isRecord(item) || !isOneOf(SETTING_KEYS, item["setting"])) return null
    const text = (key: string) => (typeof item[key] === "string" ? item[key] : null)
    changes.push({
      key: item["setting"],
      before: text("before"),
      requested: text("requested"),
      after: text("after"),
    })
  }
  const text = (key: string) => (typeof value[key] === "string" ? value[key] : null)
  return {
    id: value["ad_id"],
    name: isNonEmptyString(value["name"]) ? value["name"] : value["ad_id"],
    changes,
    outcome: value["outcome"],
    errorCode: text("error_code"),
    message: text("message"),
  }
}
