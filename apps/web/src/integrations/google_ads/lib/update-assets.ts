// apps/web/src/integrations/google_ads/lib/update-assets.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import type { ParentRow } from "@/integrations/ads/components/parent-table"
import type { CancelCard } from "@/integrations/ads/lib/cancelled-rows"
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
import { googleAdsId, textOrNull } from "@/integrations/google_ads/lib/field-values"
import {
  ASSET_TYPE_LABELS,
  ASSET_TYPES,
  assetListProblems,
  blankIsNull,
  CONTENT_TYPE_VALUES,
  draftAssetLabel,
  draftAssetType,
  fieldProblem,
  MAX_ASSETS_PER_TARGET,
  newAssetKey,
  parseContentAsset,
  sitelinkAdvice,
  type AssetType,
  type ContentType,
} from "@/integrations/google_ads/lib/new-assets"
import { isRecord } from "@/lib/guards"

export type AssetTargetKind = "campaign" | "ad_group"
type LinkAction = "add" | "remove"
// `unchecked` waits for a check of an edit; `unavailable` is a check that gave no answer.
type CheckState = "unchecked" | "unavailable"
type LinkState = "change" | "already_set" | "not_found" | CheckState

export const TARGET_KIND_LABELS: Record<AssetTargetKind, string> = {
  ad_group: "Ad Group",
  campaign: "Campaign",
}

// The most targets and links one request takes.
const MAX_TARGETS = 100
const MAX_LINKS = 1_000

const UNAVAILABLE =
  "Google Ads couldn't check this. Check again, or ask the agent to prepare the change again."

// How the prompt and the parent table count each type.
const TYPE_NOUNS: Record<AssetType, string> = {
  CALL: "phone number",
  CALLOUT: "callout",
  IMAGE: "image",
  PRICE: "price list",
  SITELINK: "sitelink",
  STRUCTURED_SNIPPET: "structured snippet",
}

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
  | {
      kind: "existing"
      // Set for an image linked as the campaign's business logo.
      businessLogo: boolean
      key: string
      ref: AssetRef
      value: Record<string, unknown>
    }

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
  state: Exclude<LinkState, CheckState>
}

type TargetCheck =
  | { unavailable: true }
  | {
      unavailable: false
      campaignName: string | null
      name: string
      now: Partial<Record<AssetType, number>>
      problem: string | null
      rows: CheckRow[]
    }

type ChangeCheck =
  | { unavailable: true }
  | {
      unavailable: false
      // Linked to the whole account, so it shows on every campaign without its own.
      accountLevel: boolean
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
  return ASSET_TYPES.find((type) => type === value) ?? null
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

function parseAddition(value: unknown): Addition | null {
  if (!isRecord(value)) return null
  if (value["type"] === "existing") {
    const ref = parseRef(value["asset"])
    const businessLogo = value["field_type"] === "BUSINESS_LOGO"
    return ref ? { businessLogo, key: `asset:${ref.assetId}`, kind: "existing", ref, value } : null
  }
  const asset = parseContentAsset(value)
  if (asset === null) return null
  return {
    assetType: draftAssetType(asset),
    key: newAssetKey(asset),
    kind: "new",
    label: draftAssetLabel(asset),
    value,
  }
}

function contentDraft(type: AssetType, content: Record<string, unknown>) {
  return type === "IMAGE" ? null : { ...content, type: CONTENT_TYPE_VALUES[type] }
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
  const draft = contentDraft(ref.assetType, content)
  return {
    assetType: ref.assetType,
    content,
    key: `customers/${ref.customerId}/assets/${ref.assetId}`,
    label: (draft ? draftAssetLabel(draft) : "") || ref.label,
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
    now: Object.fromEntries(ASSET_TYPES.map((type) => [type, count(now[type])])),
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
    accountLevel: value["account_level"] === true,
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

export type LinkRow = {
  action: LinkAction
  assetType: AssetType
  // The new asset's key, or `asset:{id}` for an existing one.
  assetKey: string
  // An image linked as the business logo rather than beside ads.
  businessLogo: boolean
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

function linkId(targetKey: string, action: LinkAction, assetKey: string): string {
  return `${targetKey}|${action}|${assetKey}`
}

// A null check is an edited target, which waits for a new one.
function entryRows(entry: AssetTarget, name: string, check: TargetCheck | null): LinkRow[] {
  const answers = new Map(
    check && !check.unavailable ? check.rows.map((row) => [`${row.action}|${row.row}`, row]) : []
  )
  const row = (
    action: LinkAction,
    assetKey: string,
    type: AssetType,
    label: string,
    isNew: boolean,
    local: string | null,
    value: Record<string, unknown>,
    businessLogo = false
  ): LinkRow => {
    const answer = answers.get(`${action}|${assetKey}`)
    const whole = check && !check.unavailable ? check.problem : null
    // A link Google gave no answer for can't be approved, as the server refuses it.
    const unavailable = check !== null && (check.unavailable || (whole === null && !answer))
    return {
      action,
      assetKey,
      assetType: type,
      businessLogo,
      cancelled: false,
      id: linkId(entry.key, action, assetKey),
      isNew,
      label: answer?.label ?? label,
      problem: local ?? (unavailable ? UNAVAILABLE : (whole ?? answer?.problem ?? null)),
      state: unavailable ? "unavailable" : (answer?.state ?? "unchecked"),
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
        : row(
            "add",
            item.key,
            item.ref.assetType,
            item.ref.label,
            false,
            null,
            item.value,
            item.businessLogo
          )
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
      ? (checked.checks.get(entry.key) ?? { unavailable: true as const })
      : null
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

/** Every new asset in the request once, by its key. */
function newAssets(args: UpdateAssetsArgs): Map<string, Record<string, unknown>> {
  const values = new Map<string, Record<string, unknown>>()
  for (const entry of args.entries)
    for (const item of entry.add) if (item.kind === "new") values.set(item.key, item.value)
  return values
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
  const values = newAssets(args)
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
  accountLevel: boolean
  before: Record<string, unknown> | null
  cancelled: boolean
  problem: string | null
  state: "change" | "already_set" | CheckState
  useCount: number
  usedIn: string[]
}

function changeFieldProblem(change: AssetChange): string | null {
  const draft = contentDraft(change.assetType, change.content)
  return draft ? fieldProblem(draft) : "An image can't be edited. Upload a new one instead."
}

/** Every content change, checked against what Google last answered for, then cancelled ones. */
export function changeRows(
  args: UpdateAssetsArgs,
  checked: UpdateAssetsArgs,
  cancelled: readonly AssetChange[] = []
): ChangeRow[] {
  const answered = new Map(checked.changes.map((change) => [change.key, change]))
  const live = args.changes.map((change): ChangeRow => {
    const same = JSON.stringify(answered.get(change.key)?.value) === JSON.stringify(change.value)
    const check = same ? checked.changeChecks.get(change.key) : undefined
    const known = check && !check.unavailable ? check : null
    // An edited change waits for a new check; one Google gave no answer for can't be approved.
    const state = same ? (known?.state ?? "unavailable") : "unchecked"
    return {
      ...change,
      accountLevel: known?.accountLevel ?? false,
      before: known?.before ?? null,
      cancelled: false,
      problem:
        changeFieldProblem(change) ??
        (state === "unavailable" ? UNAVAILABLE : (known?.problem ?? null)),
      state,
      useCount: known?.useCount ?? 0,
      usedIn: known?.usedIn ?? [],
    }
  })
  const held = new Set(live.map((row) => row.key))
  return [
    ...live,
    ...cancelled
      .filter((change) => !held.has(change.key))
      .map((change) => ({
        ...change,
        accountLevel: false,
        before: null,
        cancelled: true,
        problem: null,
        state: "unchecked" as const,
        useCount: 0,
        usedIn: [],
      })),
  ]
}

export type AssetCounts = { apply: number; problems: number; total: number }

export function assetCounts(rows: readonly LinkRow[], changes: readonly ChangeRow[]): AssetCounts {
  const live = rows.filter((row) => !row.cancelled)
  const edits = changes.filter((row) => !row.cancelled)
  const settled = (state: string) => state === "already_set" || state === "not_found"
  return {
    apply:
      live.filter((row) => row.problem === null && !settled(row.state)).length +
      edits.filter((row) => row.problem === null && row.state !== "already_set").length,
    problems:
      live.filter((row) => row.problem !== null).length +
      edits.filter((row) => row.problem !== null).length,
    total: live.length + edits.length,
  }
}

/** A target's sitelinks once its live rows apply; links already in place or not there change nothing. */
export function sitelinksAfter(now: number, rows: readonly LinkRow[]): number {
  return rows
    .filter(
      (row) => row.assetType === "SITELINK" && (row.state === "change" || row.state === "unchecked")
    )
    .reduce((total, row) => total + (row.action === "add" ? 1 : -1), now)
}

/** What a target links now, such as "4 sitelinks, 2 callouts", or "None". */
function assetsNowText(now: Partial<Record<AssetType, number>>): string {
  const parts = ASSET_TYPES.flatMap((type) => {
    const total = now[type] ?? 0
    return total > 0 ? [approvalCountLine(total, TYPE_NOUNS[type])] : []
  })
  return parts.length > 0 ? parts.join(", ") : "None"
}

/** One row per campaign or ad group, with what it links now and what changes. */
export function assetParents(
  args: UpdateAssetsArgs,
  rows: readonly LinkRow[],
  showAccount: boolean
): ParentRow[] {
  return groupedByParent(rows, (row) => row.targetKey).map(({ items, key, live }) => {
    const check = args.checks.get(key)
    const known = check && !check.unavailable ? check : null
    const sitelinks = known ? sitelinksAfter(known.now.SITELINK ?? 0, live) : null
    const advice =
      sitelinks !== null && live.some((row) => row.assetType === "SITELINK")
        ? sitelinkAdvice(sitelinks)
        : null
    const few = advice ? `${approvalCountLine(sitelinks ?? 0, "sitelink")} after. ${advice}` : null
    const account = showAccount ? (args.accounts.get(key.split("/")[1] ?? "")?.label ?? null) : null
    return {
      cancelled: live.length === 0,
      context: [known?.campaignName ?? null, few, account].filter(Boolean).join(" · ") || null,
      key,
      name: items[0]?.targetName ?? key,
      problems: live.filter((row) => row.problem !== null).length,
      values: {
        add: live.filter((row) => row.action === "add").length,
        now: known ? assetsNowText(known.now) : "",
        remove: live.filter((row) => row.action === "remove").length,
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

/** Takes link rows out of the request; a target left with nothing leaves too, kept empty for Undo. */
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
    const add = entry.add.filter((item) => !gone.has(linkId(entry.key, "add", item.key)))
    const remove = entry.remove.filter(
      (ref) => !gone.has(linkId(entry.key, "remove", `asset:${ref.assetId}`))
    )
    const next = withLists(entry, add, remove)
    if (next && add.length + remove.length > 0) return [next]
    if (next) departed.push(next)
    return []
  })
  return { departed, dropped, entries }
}

/** The target with a cancelled link back in it. */
function withLink(entry: AssetTarget, row: LinkRow): AssetTarget | null {
  const added = row.action === "add" ? parseAddition(row.value) : null
  const removed = row.action === "remove" ? parseRef(row.value) : null
  if (added && !entry.add.some((item) => item.key === added.key))
    return withLists(entry, [...entry.add, added], entry.remove)
  if (removed && !entry.remove.some((ref) => ref.assetId === removed.assetId))
    return withLists(entry, entry.add, [...entry.remove, removed])
  return null
}

/** Adds a campaign or ad group the operator found, with the new assets in the request, up to the limit. */
export function addTarget(
  args: UpdateAssetsArgs,
  kind: AssetTargetKind,
  value: Record<string, unknown>
): AssetTarget[] {
  const add = [...newAssets(args).values()].slice(0, MAX_ASSETS_PER_TARGET)
  const entry = parseTarget({ add, kind, [TARGET_FIELDS[kind].field]: value })
  const held = args.entries.some((item) => item.key === entry?.key)
  return entry && !held && entry.add.length > 0 ? [...args.entries, entry] : args.entries
}

/** Sets one field of a new asset wherever the request adds it, and in its cancelled links. */
export function editNewAsset(
  args: UpdateAssetsArgs,
  cancelled: readonly LinkRow[],
  key: string,
  field: string,
  value: unknown
): { entries: AssetTarget[]; rows: LinkRow[] } {
  const edited = (asset: Record<string, unknown>) =>
    parseAddition({ ...asset, [field]: blankIsNull(value) })
  const entries = args.entries.map((entry) => {
    if (!entry.add.some((item) => item.key === key)) return entry
    const seen = new Set<string>()
    const add = entry.add.flatMap((item) => {
      const next = item.key === key ? (edited(item.value) ?? item) : item
      // An edit that makes two assets the same leaves one, since a target takes each once.
      if (seen.has(next.key)) return []
      seen.add(next.key)
      return [next]
    })
    return withLists(entry, add, entry.remove) ?? entry
  })
  const rows = cancelled.map((row) => {
    const next = row.action === "add" && row.assetKey === key ? edited(row.value) : null
    return next?.kind === "new"
      ? {
          ...row,
          assetKey: next.key,
          id: linkId(row.targetKey, "add", next.key),
          label: next.label,
          value: next.value,
        }
      : row
  })
  return { entries, rows }
}

export function editChange(
  args: UpdateAssetsArgs,
  key: string,
  field: string,
  value: unknown
): AssetChange[] {
  return args.changes.map((change) => {
    if (change.key !== key) return change
    const content = { ...change.content, [field]: blankIsNull(value) }
    return parseChange({ ...change.value, content }) ?? change
  })
}

/** What the server refuses whatever Google answers: repeats and the request's size. */
export function assetLimitProblems(args: UpdateAssetsArgs): string[] {
  const links = args.entries.reduce(
    (total, entry) => total + entry.add.length + entry.remove.length,
    0
  )
  return [
    ...args.entries.flatMap((entry) =>
      assetListProblems(`${targetName(args, entry)} assets`, [
        entry.add.map((item) => item.key),
        entry.remove.map((ref) => `asset:${ref.assetId}`),
      ])
    ),
    ...(args.entries.length > MAX_TARGETS
      ? [`One request can change at most ${String(MAX_TARGETS)} campaigns and ad groups.`]
      : []),
    ...(links > MAX_LINKS
      ? [`One request can add or remove at most ${MAX_LINKS.toLocaleString("en-GB")} assets.`]
      : []),
  ]
}

/** How many changes have a field the server refuses, counting a new asset once per target. */
function fieldProblemCount(args: UpdateAssetsArgs): number {
  return (
    args.entries
      .flatMap((entry) => entry.add)
      .filter((item) => item.kind === "new" && fieldProblem(item.value) !== null).length +
    args.changes.filter((change) => changeFieldProblem(change) !== null).length
  )
}

/** Whether Google can check the request; the server refuses one the card knows is wrong. */
export function canCheckAssets(args: UpdateAssetsArgs): boolean {
  return assetLimitProblems(args).length === 0 && fieldProblemCount(args) === 0
}

/** True when the last check left a link or change without an answer. */
export function checkIncomplete(checked: UpdateAssetsArgs): boolean {
  return (
    linkRows(checked, checked).some((row) => row.state === "unavailable") ||
    changeRows(checked, checked).some((row) => row.state === "unavailable")
  )
}

export function needsCheck(args: UpdateAssetsArgs, checked: UpdateAssetsArgs): boolean {
  return (
    checkIncomplete(checked) ||
    JSON.stringify(serializeArgs(args)) !== JSON.stringify(serializeArgs(checked))
  )
}

/** Why the request can't be approved yet, or null. */
export function assetsBlock(
  args: UpdateAssetsArgs | null,
  checked: UpdateAssetsArgs
): string | null {
  if (args === null) return null
  // What the card knows is wrong comes first, since a check can't pass until it's fixed.
  const [limit] = assetLimitProblems(args)
  if (limit) return limit
  const fields = fieldProblemCount(args)
  if (fields > 0) return `Fix or cancel ${approvalCountLine(fields, "change")} to continue.`
  return changesBlock(
    assetCounts(linkRows(args, checked), changeRows(args, checked)),
    needsCheck(args, checked),
    "These assets are already in place."
  )
}

export function assetsApproveLabel(args: UpdateAssetsArgs): string {
  return applyChangesLabel(assetCounts(linkRows(args, args), changeRows(args, args)).apply)
}

function newCount(args: UpdateAssetsArgs, type: ContentType): number {
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
  const added = (Object.keys(CONTENT_TYPE_VALUES) as ContentType[]).flatMap((type) => {
    const total = newCount(args, type)
    return total > 0 ? [approvalCountLine(total, TYPE_NOUNS[type])] : []
  })
  const parts = [
    added.length > 0 ? `Add ${listText(added)}` : null,
    args.entries.length > 0 && added.length === 0 ? "Change the assets" : null,
    args.entries.length > 0 ? `in ${targetsText(args)}` : null,
    args.changes.length > 0
      ? `${args.entries.length > 0 ? "and edit" : "Edit"} ${approvalCountLine(args.changes.length, "asset")}`
      : null,
  ].filter(Boolean)
  return `${parts.join(" ")} in ${where}.`
}

function listText(items: readonly string[]): string {
  if (items.length <= 2) return items.join(" and ")
  return `${items.slice(0, -1).join(", ")}, and ${String(items.at(-1))}`
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

// How the shared cancelled-rows helpers read and restore this card's links.
export const ASSET_CANCEL_CARD: CancelCard<AssetTarget, LinkRow> = {
  isRow,
  parseEntry: parseTarget,
  serializeEntries: (entries) => entries.map((entry) => entry.entry),
  withRow: withLink,
}

/** The cancelled content changes the card keeps beside its cancelled links. */
export function parseCancelledChanges(value: unknown): AssetChange[] {
  return isRecord(value) ? (parseList(value["changes"], parseChange) ?? []) : []
}
