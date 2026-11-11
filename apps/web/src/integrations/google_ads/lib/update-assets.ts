// apps/web/src/integrations/google_ads/lib/update-assets.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import type { ParentRow } from "@/integrations/ads/components/parent-table"
import { collapseSpaces } from "@/integrations/ads/lib/keyword-notation"
import { groupedByParent } from "@/integrations/ads/lib/parent-rows"
import {
  accountsText,
  type GoogleAdsApprovalAccount,
  parseApprovalAccounts,
} from "@/integrations/google_ads/lib/accounts"
import {
  applyChangesLabel,
  approvalCountLine,
  changesBlock,
} from "@/integrations/google_ads/lib/copy"
import { characterCount } from "@/integrations/google_ads/lib/create-ads"
import { googleAdsId, isGoogleAdsUrl, textOrNull } from "@/integrations/google_ads/lib/field-values"
import { isRecord } from "@/lib/guards"

export type AssetType = "SITELINK" | "CALLOUT"
export type AssetTargetKind = "campaign" | "ad_group"
type LinkAction = "add" | "remove"
type LinkState = "change" | "already_set" | "not_found" | "unchecked"

export const ASSET_TYPE_LABELS: Record<AssetType, string> = {
  CALLOUT: "Callout",
  SITELINK: "Sitelink",
}

export const TARGET_KIND_LABELS: Record<AssetTargetKind, string> = {
  ad_group: "Ad Group",
  campaign: "Campaign",
}

// Each editable field's argument name, label, and character limit.
export const SITELINK_FIELDS = [
  { key: "link_text", label: "Link Text", limit: 25 },
  { key: "description1", label: "Description 1", limit: 35 },
  { key: "description2", label: "Description 2", limit: 35 },
  { key: "final_url", label: "Final URL", limit: 2048 },
] as const
export const CALLOUT_FIELDS = [{ key: "text", label: "Text", limit: 25 }] as const
export type AssetField = (typeof SITELINK_FIELDS)[number] | (typeof CALLOUT_FIELDS)[number]

// Google shows sitelinks in pairs or more, and best with four.
const SITELINKS_ADVISED = 4

const UNAVAILABLE =
  "Google Ads couldn't check this. Check again, or ask the agent to prepare the change again."

type AssetRef = {
  assetId: string
  assetType: AssetType
  customerId: string
  label: string
  value: Record<string, unknown>
}

type Addition =
  | {
      kind: "new"
      assetType: AssetType
      key: string
      label: string
      value: Record<string, unknown>
    }
  | { kind: "existing"; key: string; ref: AssetRef; value: Record<string, unknown> }

export type AssetTarget = {
  add: Addition[]
  customerId: string
  // The entry as received, so an edit keeps every reference field.
  entry: Record<string, unknown>
  // The server's name for the target, which its check is keyed by.
  key: string
  kind: AssetTargetKind
  label: string
  remove: AssetRef[]
}

export type AssetChange = {
  assetType: AssetType
  content: Record<string, unknown>
  // The asset's resource name, which its check is keyed by.
  key: string
  label: string
  ref: AssetRef
  value: Record<string, unknown>
}

type CheckRow = {
  action: LinkAction
  label: string | null
  problem: string | null
  row: string
  state: Exclude<LinkState, "unchecked">
}

type TargetCheck =
  | { unavailable: true }
  | {
      unavailable: false
      campaignName: string | null
      name: string
      now: Record<AssetType, number>
      problem: string | null
      rows: CheckRow[]
    }

type ChangeCheck =
  | { unavailable: true }
  | {
      unavailable: false
      before: Record<string, unknown> | null
      problem: string | null
      state: "change" | "already_set"
      useCount: number
      usedIn: string[]
    }

export type UpdateAssetsArgs = {
  accounts: Map<string, GoogleAdsApprovalAccount>
  changeChecks: Map<string, ChangeCheck>
  changes: AssetChange[]
  checks: Map<string, TargetCheck>
  entries: AssetTarget[]
}

function assetType(value: unknown): AssetType | null {
  return value === "SITELINK" || value === "CALLOUT" ? value : null
}

function parseRef(value: unknown): AssetRef | null {
  if (!isRecord(value)) return null
  const assetId = googleAdsId(value["asset_id"])
  const type = assetType(value["asset_type"])
  const customerId = googleAdsId(value["customer_id"])
  if (assetId === null || type === null || customerId === null) return null
  return {
    assetId,
    assetType: type,
    customerId,
    label: textOrNull(value["label"]) ?? `${ASSET_TYPE_LABELS[type]} ${assetId}`,
    value,
  }
}

function text(value: unknown): string {
  return typeof value === "string" ? collapseSpaces(value) : ""
}

/** The server's name for a new asset: its content as plain text, in a fixed order. */
export function newAssetKey(asset: Record<string, unknown>): string {
  const dates = [text(asset["start_date"]), text(asset["end_date"])]
  const parts =
    asset["type"] === "sitelink"
      ? [
          text(asset["link_text"]),
          text(asset["description1"]),
          text(asset["description2"]),
          typeof asset["final_url"] === "string" ? asset["final_url"].trim() : "",
        ]
      : [text(asset["text"])]
  return ["new", String(asset["type"]), ...parts, ...dates].join("|")
}

function parseAddition(value: unknown): Addition | null {
  if (!isRecord(value)) return null
  if (value["type"] === "existing") {
    const ref = parseRef(value["asset"])
    return ref ? { key: `asset:${ref.assetId}`, kind: "existing", ref, value } : null
  }
  if (value["type"] !== "sitelink" && value["type"] !== "callout") return null
  const type = value["type"] === "sitelink" ? "SITELINK" : "CALLOUT"
  const label = text(value[type === "SITELINK" ? "link_text" : "text"])
  return { assetType: type, key: newAssetKey(value), kind: "new", label, value }
}

const TARGET_FIELDS = {
  ad_group: { collection: "adGroups", field: "ad_group", id: "ad_group_id" },
  campaign: { collection: "campaigns", field: "campaign", id: "campaign_id" },
} as const

function parseList<T>(value: unknown, parse: (item: unknown) => T | null): T[] | null {
  if (value === undefined) return []
  if (!Array.isArray(value)) return null
  const items: T[] = []
  for (const item of value) {
    const parsed = parse(item)
    if (parsed === null) return null
    items.push(parsed)
  }
  return items
}

function parseTarget(value: unknown): AssetTarget | null {
  if (!isRecord(value)) return null
  const kind = value["kind"]
  if (kind !== "campaign" && kind !== "ad_group") return null
  const { collection, field, id } = TARGET_FIELDS[kind]
  const reference = value[field]
  if (!isRecord(reference)) return null
  const customerId = googleAdsId(reference["customer_id"])
  const targetId = googleAdsId(reference[id])
  const add = parseList(value["add"], parseAddition)
  const remove = parseList(value["remove"], parseRef)
  if (customerId === null || targetId === null || add === null || remove === null) return null
  return {
    add,
    customerId,
    entry: value,
    key: `customers/${customerId}/${collection}/${targetId}`,
    kind,
    label: textOrNull(reference["label"]) ?? `${TARGET_KIND_LABELS[kind]} ${targetId}`,
    remove,
  }
}

function parseChange(value: unknown): AssetChange | null {
  if (!isRecord(value) || !isRecord(value["content"])) return null
  const ref = parseRef(value["asset"])
  if (ref === null) return null
  const content = value["content"]
  return {
    assetType: ref.assetType,
    content,
    key: `customers/${ref.customerId}/assets/${ref.assetId}`,
    label: text(content[ref.assetType === "SITELINK" ? "link_text" : "text"]) || ref.label,
    ref,
    value,
  }
}

function parseCheckRow(value: unknown): CheckRow | null {
  if (!isRecord(value)) return null
  const { action, state } = value
  const row = textOrNull(value["row"])
  if (
    row === null ||
    (action !== "add" && action !== "remove") ||
    (state !== "change" && state !== "already_set" && state !== "not_found")
  )
    return null
  return {
    action,
    label: textOrNull(value["label"]),
    problem: textOrNull(value["problem"]),
    row,
    state,
  }
}

function count(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : 0
}

function parseTargetCheck(value: unknown): TargetCheck {
  if (!isRecord(value) || value["unavailable"] !== false) return { unavailable: true }
  const now = isRecord(value["now"]) ? value["now"] : {}
  const rows = Array.isArray(value["rows"]) ? value["rows"] : []
  return {
    unavailable: false,
    campaignName: textOrNull(value["campaign_name"]),
    name: textOrNull(value["name"]) ?? "",
    now: { CALLOUT: count(now["CALLOUT"]), SITELINK: count(now["SITELINK"]) },
    problem: textOrNull(value["problem"]),
    rows: rows.flatMap((row) => parseCheckRow(row) ?? []),
  }
}

function parseChangeCheck(value: unknown): ChangeCheck {
  if (!isRecord(value) || value["unavailable"] !== false) return { unavailable: true }
  const usedIn = Array.isArray(value["used_in"])
    ? value["used_in"].filter((name): name is string => typeof name === "string")
    : []
  return {
    unavailable: false,
    before: isRecord(value["before"]) ? value["before"] : null,
    problem: textOrNull(value["problem"]),
    state: value["state"] === "already_set" ? "already_set" : "change",
    useCount: count(value["use_count"]),
    usedIn,
  }
}

function checkMap<T>(value: unknown, parse: (item: unknown) => T): Map<string, T> {
  return new Map(Object.entries(isRecord(value) ? value : {}).map(([k, v]) => [k, parse(v)]))
}

/** Reads `entries` and `change` with the trusted `_accounts` and checks beside them; null when malformed. */
export function parseUpdateAssetsArgs(value: unknown): UpdateAssetsArgs | null {
  if (!isRecord(value)) return null
  const entries = parseList(value["entries"], parseTarget)
  const changes = parseList(value["change"], parseChange)
  if (entries === null || changes === null) return null
  return {
    accounts: parseApprovalAccounts(value["_accounts"]),
    changeChecks: checkMap(value["_changes"], parseChangeCheck),
    changes,
    checks: checkMap(value["_checks"], parseTargetCheck),
    entries,
  }
}

export function serializeArgs(args: Pick<UpdateAssetsArgs, "changes" | "entries">) {
  return {
    change: args.changes.map((change) => change.value),
    entries: args.entries.map((entry) => entry.entry),
  }
}

/** Why a new or edited asset's fields can't be sent, or null. */
export function fieldProblem(asset: Record<string, unknown>): string | null {
  const fields = asset["type"] === "sitelink" ? SITELINK_FIELDS : CALLOUT_FIELDS
  for (const field of fields) {
    const value = field.key === "final_url" ? text(asset[field.key]).trim() : text(asset[field.key])
    const length = characterCount(value)
    const optional = field.key === "description1" || field.key === "description2"
    if (length === 0 && !optional) return `${field.label} is required.`
    if (length > field.limit)
      return `${field.label} is ${String(length)} of ${String(field.limit)} characters.`
    if (field.key === "final_url" && !isGoogleAdsUrl(value))
      return "Enter a complete web address, starting with https://."
  }
  if (asset["type"] === "sitelink" && !text(asset["description1"]) !== !text(asset["description2"]))
    return "Add both description lines, or neither."
  return null
}

export type LinkRow = {
  action: LinkAction
  assetType: AssetType
  // The new asset's key, or `asset:{id}` for an existing one.
  assetKey: string
  cancelled: boolean
  id: string
  isNew: boolean
  label: string
  problem: string | null
  state: LinkState
  targetKey: string
  targetKind: AssetTargetKind
  targetName: string
  // The added item or removed reference as sent, so Undo can put it back.
  value: Record<string, unknown>
}

function targetName(args: UpdateAssetsArgs, entry: AssetTarget): string {
  const check = args.checks.get(entry.key)
  return check && !check.unavailable && check.name ? check.name : entry.label
}

function entryRows(entry: AssetTarget, name: string, check: TargetCheck | undefined): LinkRow[] {
  const shown = new Map(
    check && !check.unavailable ? check.rows.map((row) => [`${row.action}|${row.row}`, row]) : []
  )
  const row = (
    action: LinkAction,
    assetKey: string,
    type: AssetType,
    label: string,
    isNew: boolean,
    local: string | null,
    value: Record<string, unknown>
  ): LinkRow => {
    const checked = shown.get(`${action}|${assetKey}`)
    const problem =
      local ??
      (check === undefined
        ? null
        : check.unavailable
          ? UNAVAILABLE
          : (check.problem ?? checked?.problem ?? null))
    return {
      action,
      assetKey,
      assetType: type,
      cancelled: false,
      id: `${entry.key}|${action}|${assetKey}`,
      isNew,
      label: checked?.label ?? label,
      problem,
      state: checked?.state ?? "unchecked",
      targetKey: entry.key,
      targetKind: entry.kind,
      targetName: name,
      value,
    }
  }
  return [
    ...entry.remove.map((ref) =>
      row("remove", `asset:${ref.assetId}`, ref.assetType, ref.label, false, null, ref.value)
    ),
    ...entry.add.map((item) =>
      item.kind === "new"
        ? row(
            "add",
            item.key,
            item.assetType,
            item.label,
            true,
            fieldProblem(item.value),
            item.value
          )
        : row("add", item.key, item.ref.assetType, item.ref.label, false, null, item.value)
    ),
  ]
}

function sameEntry(a: AssetTarget | undefined, b: AssetTarget): boolean {
  return JSON.stringify(a?.entry) === JSON.stringify(b.entry)
}

/** Every link the request adds or removes, checked against what Google last answered for, then cancelled ones. */
export function linkRows(
  args: UpdateAssetsArgs,
  checked: UpdateAssetsArgs,
  cancelled: readonly LinkRow[] = []
): LinkRow[] {
  const answered = new Map(checked.entries.map((entry) => [entry.key, entry]))
  const live = args.entries.flatMap((entry) => {
    // An edited target waits for a new check, so its old answers don't apply.
    const check = sameEntry(answered.get(entry.key), entry)
      ? checked.checks.get(entry.key)
      : undefined
    return entryRows(entry, targetName(checked, entry), check)
  })
  const held = new Set(live.map((row) => row.id))
  return [
    ...live,
    ...cancelled
      .filter((row) => !held.has(row.id))
      .map((row) => ({ ...row, cancelled: true, problem: null })),
  ]
}

export type NewAssetRow = {
  assetType: AssetType
  key: string
  problem: string | null
  targets: number
  value: Record<string, unknown>
}

/** Each new asset once, however many targets it's added to, with the first problem any of them has. */
export function newAssetRows(rows: readonly LinkRow[], args: UpdateAssetsArgs): NewAssetRow[] {
  const values = new Map<string, Record<string, unknown>>()
  for (const entry of args.entries)
    for (const item of entry.add) if (item.kind === "new") values.set(item.key, item.value)
  const byKey = new Map<string, NewAssetRow>()
  for (const row of rows) {
    const value = values.get(row.assetKey)
    if (!row.isNew || row.cancelled || value === undefined) continue
    const current = byKey.get(row.assetKey)
    byKey.set(row.assetKey, {
      assetType: row.assetType,
      key: row.assetKey,
      problem: current?.problem ?? row.problem,
      targets: (current?.targets ?? 0) + 1,
      value,
    })
  }
  return [...byKey.values()]
}

export type ChangeRow = AssetChange & {
  before: Record<string, unknown> | null
  problem: string | null
  state: "change" | "already_set" | "unchecked"
  useCount: number
  usedIn: string[]
}

export function changeRows(args: UpdateAssetsArgs, checked: UpdateAssetsArgs): ChangeRow[] {
  const answered = new Map(checked.changes.map((change) => [change.key, change]))
  return args.changes.map((change) => {
    const same = JSON.stringify(answered.get(change.key)?.value) === JSON.stringify(change.value)
    const check = same ? checked.changeChecks.get(change.key) : undefined
    const known = check && !check.unavailable ? check : null
    return {
      ...change,
      before: known?.before ?? null,
      problem:
        fieldProblem({
          ...change.content,
          type: change.assetType === "SITELINK" ? "sitelink" : "callout",
        }) ?? (check?.unavailable ? UNAVAILABLE : (known?.problem ?? null)),
      state: known?.state ?? "unchecked",
      useCount: known?.useCount ?? 0,
      usedIn: known?.usedIn ?? [],
    }
  })
}

export type AssetCounts = { apply: number; problems: number; total: number }

export function assetCounts(rows: readonly LinkRow[], changes: readonly ChangeRow[]): AssetCounts {
  const live = rows.filter((row) => !row.cancelled)
  const settled = (state: string) => state === "already_set" || state === "not_found"
  return {
    apply:
      live.filter((row) => row.problem === null && !settled(row.state)).length +
      changes.filter((row) => row.problem === null && row.state !== "already_set").length,
    problems:
      live.filter((row) => row.problem !== null).length +
      changes.filter((row) => row.problem !== null).length,
    total: live.length + changes.length,
  }
}

/** One row per campaign or ad group, with its sitelinks and callouts now and what changes. */
export function assetParents(
  args: UpdateAssetsArgs,
  rows: readonly LinkRow[],
  showAccount: boolean
): ParentRow[] {
  return groupedByParent(rows, (row) => row.targetKey).map(({ items, key, live }) => {
    const check = args.checks.get(key)
    const known = check && !check.unavailable ? check : null
    // Links already in place or not there change nothing.
    const delta = (type: AssetType) =>
      live
        .filter(
          (row) => row.assetType === type && (row.state === "change" || row.state === "unchecked")
        )
        .reduce((total, row) => total + (row.action === "add" ? 1 : -1), 0)
    const sitelinks = known ? known.now.SITELINK + delta("SITELINK") : null
    const few =
      sitelinks !== null &&
      sitelinks < SITELINKS_ADVISED &&
      live.some((row) => row.assetType === "SITELINK")
        ? `${approvalCountLine(sitelinks, "sitelink")} after. Google shows sitelinks best with 4 or more.`
        : null
    const account = showAccount ? (args.accounts.get(key.split("/")[1] ?? "")?.label ?? null) : null
    return {
      cancelled: live.length === 0,
      context: [known?.campaignName ?? null, few, account].filter(Boolean).join(" · ") || null,
      key,
      name: items[0]?.targetName ?? key,
      problems: live.filter((row) => row.problem !== null).length,
      values: {
        add: live.filter((row) => row.action === "add").length,
        callouts: known ? known.now.CALLOUT : "",
        remove: live.filter((row) => row.action === "remove").length,
        sitelinks: known ? known.now.SITELINK : "",
      },
    }
  })
}

function withLists(entry: AssetTarget, add: Addition[], remove: AssetRef[]): AssetTarget | null {
  const fields: Record<string, unknown> = { ...entry.entry }
  // Only a list that changed is rewritten, so an untouched target keeps what Google checked.
  if (add.length !== entry.add.length || add.some((item, at) => item !== entry.add[at]))
    fields["add"] = add.map((item) => item.value)
  if (remove.length !== entry.remove.length) fields["remove"] = remove.map((ref) => ref.value)
  return parseTarget(fields)
}

export type CancelledChanges = { entries: AssetTarget[]; rows: LinkRow[] }

/** Takes link rows out of the request; a target left with nothing leaves too, kept for Undo. */
export function cancelLinks(
  args: UpdateAssetsArgs,
  rows: readonly LinkRow[],
  ids: ReadonlySet<string>
): { entries: AssetTarget[]; departed: AssetTarget[]; dropped: LinkRow[] } {
  const dropped = rows.filter((row) => ids.has(row.id) && !row.cancelled)
  const departed: AssetTarget[] = []
  const entries = args.entries.flatMap((entry) => {
    const gone = new Set(dropped.filter((row) => row.targetKey === entry.key).map((row) => row.id))
    if (gone.size === 0) return [entry]
    const id = (action: LinkAction, key: string) => `${entry.key}|${action}|${key}`
    const add = entry.add.filter((item) => !gone.has(id("add", item.key)))
    const remove = entry.remove.filter((ref) => !gone.has(id("remove", `asset:${ref.assetId}`)))
    const next = add.length + remove.length > 0 ? withLists(entry, add, remove) : null
    if (next) return [next]
    departed.push(entry)
    return []
  })
  return { departed, dropped, entries }
}

/** Puts a cancelled link back, or its whole target when the target left the request. */
export function restoreLink(
  args: UpdateAssetsArgs,
  departed: readonly AssetTarget[],
  row: LinkRow
): AssetTarget[] {
  const entry = args.entries.find((item) => item.key === row.targetKey)
  if (!entry) {
    const whole = departed.find((item) => item.key === row.targetKey)
    return whole ? [...args.entries, whole] : args.entries
  }
  const added = row.action === "add" ? parseAddition(row.value) : null
  const removed = row.action === "remove" ? parseRef(row.value) : null
  const next =
    added && !entry.add.some((item) => item.key === added.key)
      ? withLists(entry, [...entry.add, added], entry.remove)
      : removed && !entry.remove.some((ref) => ref.assetId === removed.assetId)
        ? withLists(entry, entry.add, [...entry.remove, removed])
        : null
  return args.entries.map((item) => (item === entry && next ? next : item))
}

/** Puts back every cancelled link of one target, bringing the target back if it left. */
export function restoreTarget(
  args: UpdateAssetsArgs,
  departed: readonly AssetTarget[],
  rows: readonly LinkRow[],
  targetKey: string
): AssetTarget[] {
  return rows
    .filter((row) => row.cancelled && row.targetKey === targetKey)
    .reduce((entries, row) => restoreLink({ ...args, entries }, departed, row), args.entries)
}

/** Adds a campaign or ad group the operator found, with every new asset in the request. */
export function addTarget(
  args: UpdateAssetsArgs,
  kind: AssetTargetKind,
  value: Record<string, unknown>
): AssetTarget[] {
  const assets = new Map<string, Record<string, unknown>>()
  for (const entry of args.entries)
    for (const item of entry.add) if (item.kind === "new") assets.set(item.key, item.value)
  const entry = parseTarget({ add: [...assets.values()], kind, [TARGET_FIELDS[kind].field]: value })
  const held = args.entries.some((item) => item.key === entry?.key)
  return entry && !held && entry.add.length > 0 ? [...args.entries, entry] : args.entries
}

/** Sets one field of a new asset wherever the request adds it. */
export function editNewAsset(
  args: UpdateAssetsArgs,
  key: string,
  field: string,
  value: string
): AssetTarget[] {
  return args.entries.map((entry) => {
    if (!entry.add.some((item) => item.key === key)) return entry
    const add = entry.add.map((item) => {
      if (item.key !== key) return item
      const next = { ...item.value, [field]: value.trim() === "" ? null : value }
      return parseAddition(next) ?? item
    })
    return withLists(entry, add, entry.remove) ?? entry
  })
}

export function editChange(
  args: UpdateAssetsArgs,
  key: string,
  field: string,
  value: string
): AssetChange[] {
  return args.changes.map((change) => {
    if (change.key !== key) return change
    const content = { ...change.content, [field]: value.trim() === "" ? null : value }
    return parseChange({ ...change.value, content }) ?? change
  })
}

export function needsCheck(args: UpdateAssetsArgs, checked: UpdateAssetsArgs): boolean {
  return (
    [...checked.checks.values(), ...checked.changeChecks.values()].some(
      (check) => check.unavailable
    ) || JSON.stringify(serializeArgs(args)) !== JSON.stringify(serializeArgs(checked))
  )
}

/** Why the request can't be approved yet, or null. */
export function assetsBlock(
  args: UpdateAssetsArgs | null,
  checked: UpdateAssetsArgs
): string | null {
  if (args === null) return null
  return changesBlock(
    assetCounts(linkRows(args, checked), changeRows(args, checked)),
    needsCheck(args, checked),
    "These assets are already in place."
  )
}

export function assetsApproveLabel(args: UpdateAssetsArgs): string {
  return applyChangesLabel(assetCounts(linkRows(args, args), changeRows(args, args)).apply)
}

function newCount(args: UpdateAssetsArgs, type: AssetType): number {
  return new Set(
    args.entries.flatMap((entry) =>
      entry.add.filter((item) => item.kind === "new" && item.assetType === type).map((i) => i.key)
    )
  ).size
}

function targetsText(args: UpdateAssetsArgs): string {
  const [first] = args.entries
  if (args.entries.length === 1 && first) return targetName(args, first)
  const parts = (["campaign", "ad_group"] as const).flatMap((kind) => {
    const total = args.entries.filter((entry) => entry.kind === kind).length
    return total > 0
      ? [approvalCountLine(total, kind === "campaign" ? "campaign" : "ad group")]
      : []
  })
  return parts.join(" and ")
}

export function assetsPrompt(args: UpdateAssetsArgs): string {
  if (args.entries.length === 0 && args.changes.length === 0) return "Nothing is left to change."
  const where = accountsText(args.accounts, [
    ...args.entries.map((entry) => entry.customerId),
    ...args.changes.map((change) => change.key.split("/")[1] ?? ""),
  ])
  const added = [
    newCount(args, "SITELINK") > 0
      ? approvalCountLine(newCount(args, "SITELINK"), "sitelink")
      : null,
    newCount(args, "CALLOUT") > 0 ? approvalCountLine(newCount(args, "CALLOUT"), "callout") : null,
  ].filter(Boolean)
  const parts = [
    added.length > 0 ? `Add ${added.join(" and ")}` : null,
    args.entries.length > 0 && added.length === 0 ? "Change the assets" : null,
    args.entries.length > 0 ? `in ${targetsText(args)}` : null,
    args.changes.length > 0
      ? `${args.entries.length > 0 ? "and edit" : "Edit"} ${approvalCountLine(args.changes.length, "asset")}`
      : null,
  ].filter(Boolean)
  return `${parts.join(" ")} in ${where}.`
}

export function assetsDetails(args: UpdateAssetsArgs | null): FanOutDetail[] {
  return args
    ? [
        { label: "Targets", value: String(args.entries.length) },
        ...(args.changes.length > 0
          ? [{ label: "Edited", value: String(args.changes.length) }]
          : []),
      ]
    : []
}

function isRow(value: unknown): value is LinkRow {
  return (
    isRecord(value) && typeof value["id"] === "string" && typeof value["targetKey"] === "string"
  )
}

/** The card's own record of cancelled rows and targets, which survives a check's redraw. */
export function parseCancelled(value: unknown): CancelledChanges {
  if (!isRecord(value)) return { entries: [], rows: [] }
  const entries = Array.isArray(value["entries"]) ? value["entries"] : []
  const rows = Array.isArray(value["rows"]) ? value["rows"] : []
  return { entries: entries.flatMap((entry) => parseTarget(entry) ?? []), rows: rows.filter(isRow) }
}

export function serializeCancelled(cancelled: CancelledChanges): Record<string, unknown> {
  return { entries: cancelled.entries.map((entry) => entry.entry), rows: cancelled.rows }
}
