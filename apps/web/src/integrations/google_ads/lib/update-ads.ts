// apps/web/src/integrations/google_ads/lib/update-ads.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import type { ParentRow } from "@/integrations/ads/components/parent-table"
import { groupedByParent } from "@/integrations/ads/lib/parent-rows"
import {
  accountsText,
  type GoogleAdsApprovalAccount,
  parseCheckedEntries,
} from "@/integrations/google_ads/lib/accounts"
import { approvalCountLine, unavailableProblem } from "@/integrations/google_ads/lib/copy"
import {
  type AdCopy,
  characterCount,
  DESCRIPTION_LIMITS,
  HEADLINE_LIMITS,
  parseTextAssets,
  type TextAsset,
} from "@/integrations/google_ads/lib/create-ads"
import { googleAdsId, isGoogleAdsUrl, textOrNull } from "@/integrations/google_ads/lib/field-values"
import { isRecord } from "@/lib/guards"

/** An ad's copy and links as the server sends them: no path is null, and one final URL. */
export type LiveCopy = {
  descriptions: TextAsset[]
  finalUrl: string | null
  headlines: TextAsset[]
  path1: string | null
  path2: string | null
}

/** One entry's edits in the tool's terms; a key is present only when the entry names it. */
export type AdEdits = {
  add_descriptions?: TextAsset[]
  add_headlines?: TextAsset[]
  final_url?: string
  path1?: string
  path2?: string
  pins?: TextAsset[]
  remove_descriptions?: string[]
  remove_headlines?: string[]
}

type AdChange = {
  adGroupId: string
  adId: string
  customerId: string
  edits: AdEdits
  // The entry as received, so an edit keeps every reference field.
  entry: Record<string, unknown>
  // The `adGroupAds` resource name, which keys the checks.
  key: string
  label: string
}

type AdCheck =
  | { unavailable: true }
  | {
      unavailable: false
      adGroupName: string | null
      campaignName: string | null
      current: LiveCopy | null
      name: string | null
      problem: string | null
      problems: string[]
      requested: AdEdits
    }

export type UpdateAdsArgs = {
  accounts: Map<string, GoogleAdsApprovalAccount>
  changes: AdChange[]
  checks: Map<string, AdCheck>
}

export type AdRow = {
  adGroupName: string
  after: LiveCopy | null
  campaignName: string
  cancelled: boolean
  change: AdChange
  current: LiveCopy | null
  key: string
  name: string
  // Blocks approval while there are any.
  problems: string[]
  // The merge leaves the ad as it is, so nothing is sent for it.
  unchanged: boolean
}

export type AdCounts = { ads: number; apply: number; campaigns: number; problems: number }

const UNAVAILABLE = unavailableProblem("ad")
const PATH_LENGTH = 15
const EDIT_KEYS = [
  "add_headlines",
  "remove_headlines",
  "add_descriptions",
  "remove_descriptions",
  "pins",
  "path1",
  "path2",
  "final_url",
] as const

function parseTexts(value: unknown): string[] | null {
  return Array.isArray(value) && value.every((item) => typeof item === "string") ? value : null
}

function parseCopy(value: unknown): LiveCopy | null {
  if (!isRecord(value)) return null
  const headlines = parseTextAssets(value["headlines"])
  const descriptions = parseTextAssets(value["descriptions"])
  if (headlines === null || descriptions === null) return null
  return {
    descriptions,
    finalUrl: textOrNull(value["final_url"]),
    headlines,
    path1: textOrNull(value["path1"]),
    path2: textOrNull(value["path2"]),
  }
}

/** The edits an entry names, read the way the server reads them: trimmed, empty lists dropped. */
function editsOf(entry: Record<string, unknown>): AdEdits {
  const edits: AdEdits = {}
  const trimmed = (items: TextAsset[]) => items.map((item) => ({ ...item, text: item.text.trim() }))
  for (const key of ["add_headlines", "add_descriptions", "pins"] as const) {
    const assets = parseTextAssets(entry[key])
    if (assets?.length) edits[key] = trimmed(assets)
  }
  for (const key of ["remove_headlines", "remove_descriptions"] as const) {
    const texts = parseTexts(entry[key])
    if (texts?.length) edits[key] = texts.map((item) => item.trim())
  }
  for (const key of ["path1", "path2", "final_url"] as const) {
    const value = entry[key]
    if (typeof value === "string") edits[key] = value.trim()
  }
  return edits
}

function parseChange(value: unknown): AdChange | null {
  if (!isRecord(value) || !isRecord(value["ad"])) return null
  const reference = value["ad"]
  const customerId = googleAdsId(reference["customer_id"])
  const adGroupId = googleAdsId(reference["ad_group_id"])
  const adId = googleAdsId(reference["ad_id"])
  if (customerId === null || adGroupId === null || adId === null) return null
  return {
    adGroupId,
    adId,
    customerId,
    edits: editsOf(value),
    entry: value,
    key: `customers/${customerId}/adGroupAds/${adGroupId}~${adId}`,
    label: textOrNull(reference["label"]) ?? `Ad ${adId}`,
  }
}

function parseCheck(value: unknown): AdCheck {
  if (!isRecord(value) || value["unavailable"] !== false) return { unavailable: true }
  return {
    unavailable: false,
    adGroupName: textOrNull(value["ad_group_name"]),
    campaignName: textOrNull(value["campaign_name"]),
    current: parseCopy(value["current"]),
    name: textOrNull(value["name"]),
    problem: textOrNull(value["problem"]),
    problems: parseTexts(value["problems"]) ?? [],
    requested: isRecord(value["requested"]) ? editsOf(value["requested"]) : {},
  }
}

/** Reads `changes` with the trusted `_accounts` and `_checks` beside it; null when malformed. */
export function parseUpdateAdsArgs(value: unknown): UpdateAdsArgs | null {
  const parsed = parseCheckedEntries(value, "changes", parseChange, parseCheck)
  return parsed && { accounts: parsed.accounts, checks: parsed.checks, changes: parsed.entries }
}

/** The same edits in a fixed order, so two can be compared whatever order their keys came in. */
function editsSignature(edits: AdEdits): string {
  return JSON.stringify(EDIT_KEYS.map((key) => edits[key] ?? null))
}

function mergedAssets(
  noun: string,
  live: readonly TextAsset[],
  removed: readonly string[] = [],
  added: readonly TextAsset[] = [],
  problems: string[]
): TextAsset[] {
  const liveTexts = live.map((item) => item.text)
  for (const item of removed)
    if (!liveTexts.includes(item)) problems.push(`This ad has no ${noun} “${item}” to remove.`)
  const queue = added.map((item) => ({ ...item }))
  const merged: TextAsset[] = []
  for (const item of live) {
    if (!removed.includes(item.text)) merged.push({ ...item })
    else {
      const next = queue.shift()
      if (next) merged.push(next)
    }
  }
  merged.push(...queue)
  const kept = new Set(liveTexts.filter((item) => !removed.includes(item)))
  const texts = merged.map((item) => item.text)
  for (const item of new Set(texts.filter((entry, at) => texts.indexOf(entry) !== at)))
    problems.push(
      kept.has(item)
        ? `This ad already has the ${noun} “${item}”.`
        : `The ${noun} “${item}” is added twice.`
    )
  return merged
}

function pin(
  item: TextAsset,
  headlines: TextAsset[],
  descriptions: TextAsset[],
  problems: string[]
) {
  const [lists, noun] =
    item.pin === null
      ? [[headlines, descriptions], "headline or description"]
      : item.pin.startsWith("HEADLINE")
        ? [[headlines], "headline"]
        : [[descriptions], "description"]
  const found = lists.flat().filter((asset) => asset.text === item.text)
  if (found.length === 0) problems.push(`This ad has no ${noun} “${item.text}” to pin.`)
  for (const asset of found) asset.pin = item.pin
}

/**
 * Applies one entry's edits to the live copy as the server does, with why it can't be sent.
 *
 * An added headline or description takes the place of a removed one, in order, and the rest
 * go at the end.
 */
export function mergedCopy(
  current: LiveCopy,
  edits: AdEdits
): { after: LiveCopy; problems: string[] } {
  const problems: string[] = []
  const headlines = mergedAssets(
    "headline",
    current.headlines,
    edits.remove_headlines,
    edits.add_headlines,
    problems
  )
  const descriptions = mergedAssets(
    "description",
    current.descriptions,
    edits.remove_descriptions,
    edits.add_descriptions,
    problems
  )
  for (const item of edits.pins ?? []) pin(item, headlines, descriptions, problems)
  for (const [label, assets, limits] of [
    ["headlines", headlines, HEADLINE_LIMITS],
    ["descriptions", descriptions, DESCRIPTION_LIMITS],
  ] as const)
    if (assets.length < limits.min || assets.length > limits.max)
      problems.push(
        `An ad needs ${String(limits.min)} to ${String(limits.max)} ${label}. This edit leaves ${String(assets.length)}.`
      )
  const after: LiveCopy = {
    descriptions,
    finalUrl: edits.final_url ?? current.finalUrl,
    headlines,
    path1: edits.path1 === undefined ? current.path1 : edits.path1 || null,
    path2: edits.path2 === undefined ? current.path2 : edits.path2 || null,
  }
  if (after.path2 && !after.path1) problems.push("Set path 1 before path 2.")
  return { after, problems }
}

/** What the card can tell is wrong with merged copy before Google sees it. */
function copyProblems(copy: LiveCopy, edits: AdEdits): string[] {
  const problems: string[] = []
  for (const [noun, assets, limit] of [
    ["Headline", copy.headlines, HEADLINE_LIMITS.length],
    ["Description", copy.descriptions, DESCRIPTION_LIMITS.length],
  ] as const)
    assets.forEach((asset, index) => {
      const count = characterCount(asset.text.trim())
      const at = `${noun} ${String(index + 1)}`
      if (count === 0) problems.push(`${at} is empty.`)
      if (count > limit)
        problems.push(`${at} is ${String(count)} characters. The limit is ${String(limit)}.`)
    })
  for (const [label, path] of [
    ["Path 1", copy.path1],
    ["Path 2", copy.path2],
  ] as const) {
    const count = characterCount(path ?? "")
    if (count > PATH_LENGTH)
      problems.push(`${label} is ${String(count)} characters. The limit is ${String(PATH_LENGTH)}.`)
  }
  if (edits.final_url !== undefined && !isGoogleAdsUrl(edits.final_url))
    problems.push("Enter a final URL starting with http:// or https://.")
  return problems
}

function sameCopy(a: LiveCopy | null, b: LiveCopy | null): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

function rowOf(change: AdChange, check: AdCheck | undefined, cancelled: boolean): AdRow {
  const live = check && !check.unavailable ? check : null
  const current = live?.current ?? null
  const merged = current ? mergedCopy(current, change.edits) : null
  // Google answered for the edits it was checked with, so an edited ad waits for a new check.
  const checked = live !== null && editsSignature(live.requested) === editsSignature(change.edits)
  const problems = live === null ? [UNAVAILABLE] : []
  if (live?.problem) problems.push(live.problem)
  if (merged) problems.push(...merged.problems, ...copyProblems(merged.after, change.edits))
  if (checked) problems.push(...live.problems)
  return {
    adGroupName: live?.adGroupName ?? "",
    after: merged?.after ?? null,
    campaignName: live?.campaignName ?? "",
    cancelled,
    change,
    current,
    key: change.key,
    name: live?.name ?? change.label,
    problems: [...new Set(problems)],
    unchanged: merged !== null && sameCopy(merged.after, current),
  }
}

/** One row per ad, with cancelled ads after the ones still requested. */
export function adRows(
  args: UpdateAdsArgs,
  checked: UpdateAdsArgs,
  cancelled: readonly Record<string, unknown>[] = []
): AdRow[] {
  const rows = args.changes.map((change) => rowOf(change, checked.checks.get(change.key), false))
  const live = new Set(rows.map((row) => row.key))
  for (const entry of cancelled) {
    const change = parseChange(entry)
    if (change && !live.has(change.key))
      rows.push(rowOf(change, checked.checks.get(change.key), true))
  }
  return rows
}

export function adCounts(rows: readonly AdRow[]): AdCounts {
  const live = rows.filter((row) => !row.cancelled)
  return {
    ads: live.length,
    apply: live.filter((row) => !row.unchanged).length,
    campaigns: new Set(live.map((row) => row.campaignName || row.key)).size,
    problems: live.filter((row) => row.problems.length > 0).length,
  }
}

/** Writes edits into a raw entry in the tool's argument shape, keeping its ad reference. */
export function withEdits(entry: Record<string, unknown>, edits: AdEdits): Record<string, unknown> {
  const kept = Object.fromEntries(
    Object.entries(entry).filter(([key]) => !(EDIT_KEYS as readonly string[]).includes(key))
  )
  return { ...kept, ...edits }
}

/** The edits that turn the live copy into the copy the operator wants. */
export function editsFor(current: LiveCopy, wanted: LiveCopy): AdEdits {
  const edits: AdEdits = {}
  const diff = (live: readonly TextAsset[], next: readonly TextAsset[]) => {
    const liveTexts = live.map((item) => item.text)
    const nextTexts = next.map((item) => item.text)
    return {
      added: next.filter((item) => !liveTexts.includes(item.text)),
      pins: next.filter((item) =>
        live.some((asset) => asset.text === item.text && asset.pin !== item.pin)
      ),
      removed: liveTexts.filter((item) => !nextTexts.includes(item)),
    }
  }
  const headlines = diff(current.headlines, wanted.headlines)
  const descriptions = diff(current.descriptions, wanted.descriptions)
  if (headlines.added.length) edits.add_headlines = headlines.added
  if (headlines.removed.length) edits.remove_headlines = headlines.removed
  if (descriptions.added.length) edits.add_descriptions = descriptions.added
  if (descriptions.removed.length) edits.remove_descriptions = descriptions.removed
  const pins = [...headlines.pins, ...descriptions.pins]
  if (pins.length) edits.pins = pins
  for (const key of ["path1", "path2"] as const)
    if ((wanted[key] ?? "") !== (current[key] ?? "")) edits[key] = wanted[key] ?? ""
  if (wanted.finalUrl !== current.finalUrl) edits.final_url = wanted.finalUrl ?? ""
  return edits
}

/** The merged assets in the order the editor last had them, which the merge doesn't keep. */
export function assetsInOrder(assets: readonly TextAsset[], order: readonly string[]): TextAsset[] {
  const place = (asset: TextAsset) => {
    const at = order.indexOf(asset.text)
    return at === -1 ? order.length : at
  }
  return [...assets].sort((a, b) => place(a) - place(b))
}

/** The edits every ad shares, when there are several ads and they all have the same ones. */
export function sharedEdits(args: UpdateAdsArgs): AdEdits | null {
  const [first, ...rest] = args.changes
  if (!first || rest.length === 0) return null
  const signature = editsSignature(first.edits)
  return rest.every((change) => editsSignature(change.edits) === signature) ? first.edits : null
}

/** What Undo can bring back: cancelled entries no longer in the request. */
export function cancelledEntries(
  retained: unknown,
  args: UpdateAdsArgs
): Record<string, unknown>[] {
  if (!Array.isArray(retained)) return []
  const current = new Set(args.changes.map((change) => change.key))
  return retained.filter(isRecord).filter((entry) => {
    const change = parseChange(entry)
    return change !== null && !current.has(change.key)
  })
}

/** The ad group an ad sits in, as the `adGroups` resource name. */
export function adGroupOf(change: AdChange): string {
  return `customers/${change.customerId}/adGroups/${change.adGroupId}`
}

/** Brings back the cancelled ads that match, after the ones still requested. */
export function restoredAds(
  args: UpdateAdsArgs,
  cancelled: readonly Record<string, unknown>[],
  match: (change: AdChange) => boolean
): { cancelled: Record<string, unknown>[]; changes: Record<string, unknown>[] } {
  const restored = cancelled.filter((entry) => {
    const change = parseChange(entry)
    return change !== null && match(change)
  })
  return {
    cancelled: cancelled.filter((entry) => !restored.includes(entry)),
    changes: [...args.changes.map((change) => change.entry), ...restored],
  }
}

export function adsNeedCheck(args: UpdateAdsArgs, checked: UpdateAdsArgs): boolean {
  const signature = (value: UpdateAdsArgs) =>
    JSON.stringify(value.changes.map((change) => [change.key, editsSignature(change.edits)]))
  return (
    [...checked.checks.values()].some((check) => check.unavailable) ||
    signature(args) !== signature(checked)
  )
}

/** Whether Google can check the request: the card finds nothing wrong with any ad's merge. */
export function canCheckAds(args: UpdateAdsArgs, checked: UpdateAdsArgs): boolean {
  return (
    args.changes.length > 0 &&
    args.changes.every((change) => {
      const check = checked.checks.get(change.key)
      const current = check && !check.unavailable ? check.current : null
      if (current === null) return true
      const merged = mergedCopy(current, change.edits)
      return [...merged.problems, ...copyProblems(merged.after, change.edits)].length === 0
    })
  )
}

/** Why the request can't be approved yet, or null. */
export function updateAdsBlock(args: UpdateAdsArgs | null, checked: UpdateAdsArgs): string | null {
  if (args === null) return null
  const counts = adCounts(adRows(args, checked))
  if (counts.ads === 0) return "Every change is cancelled. Decline this request, or undo one."
  if (adsNeedCheck(args, checked))
    return "Click Check Changes so Google can check your edits, then approve."
  if (counts.problems > 0)
    return `Fix or cancel ${approvalCountLine(counts.problems, "ad")} to continue.`
  if (counts.apply === 0) return "These ads already have this copy."
  return null
}

/** The copy as the shared search result preview takes it. */
export function previewCopy(copy: LiveCopy): AdCopy {
  return {
    descriptions: copy.descriptions,
    finalUrl: copy.finalUrl ?? "",
    headlines: copy.headlines,
    mobileFinalUrl: "",
    path1: copy.path1 ?? "",
    path2: copy.path2 ?? "",
  }
}

/** A one-headline swap, which reads better named than counted. */
function swap(edits: AdEdits): { from: string; to: string } | null {
  const keys = EDIT_KEYS.filter((key) => edits[key] !== undefined)
  const [from] = edits.remove_headlines ?? []
  const [to] = edits.add_headlines ?? []
  return keys.length === 2 &&
    edits.remove_headlines?.length === 1 &&
    edits.add_headlines?.length === 1 &&
    from !== undefined &&
    to !== undefined
    ? { from, to: to.text }
    : null
}

export function updateAdsPrompt(args: UpdateAdsArgs): string {
  const rows = adRows(args, args)
  if (rows.length === 0) return "Nothing is left to change."
  const [sole] = rows
  if (rows.length === 1 && sole)
    return sole.adGroupName
      ? `Change the copy of ${sole.name} in ${sole.adGroupName}.`
      : `Change the copy of ${sole.name}.`
  const { campaigns } = adCounts(rows)
  const where = `${approvalCountLine(rows.length, "responsive search ad")} in ${approvalCountLine(campaigns, "campaign")} in ${accountsText(
    args.accounts,
    args.changes.map((change) => change.customerId)
  )}`
  const shared = sharedEdits(args)
  return shared && swap(shared) ? `Swap one headline in ${where}.` : `Change ${where}.`
}

export function updateAdsApproveLabel(args: UpdateAdsArgs): string {
  const { apply } = adCounts(adRows(args, args))
  if (apply <= 1) return "Update Ad"
  return `Update ${String(apply)} Ads`
}

export function updateAdsBannerDetail(counts: AdCounts): string {
  return [
    `${approvalCountLine(counts.ads, "ad")} in ${approvalCountLine(counts.campaigns, "campaign")}`,
    "Google reviews each edited ad again, and the result shows where its review is.",
  ].join(" · ")
}

export function updateAdsDetails(args: UpdateAdsArgs | null): FanOutDetail[] {
  return args ? [{ label: "Ads", value: String(args.changes.length) }] : []
}

/** The edits in a line, such as `“Shop the Range” → “Free Returns”`. */
export function editsLine(edits: AdEdits): string {
  const named = swap(edits)
  if (named) return `“${named.from}” → “${named.to}”`
  const parts = [
    edits.add_headlines?.length
      ? approvalCountLine(edits.add_headlines.length, "headline") + " added"
      : null,
    edits.remove_headlines?.length
      ? approvalCountLine(edits.remove_headlines.length, "headline") + " removed"
      : null,
    edits.add_descriptions?.length
      ? approvalCountLine(edits.add_descriptions.length, "description") + " added"
      : null,
    edits.remove_descriptions?.length
      ? approvalCountLine(edits.remove_descriptions.length, "description") + " removed"
      : null,
    edits.pins?.length ? approvalCountLine(edits.pins.length, "pin") + " changed" : null,
    edits.path1 !== undefined || edits.path2 !== undefined ? "display path changed" : null,
    edits.final_url !== undefined ? "final URL changed" : null,
  ].filter((part) => part !== null)
  const line = parts.join(", ")
  return line ? line.charAt(0).toUpperCase() + line.slice(1) : "No change"
}

/** One row per ad group, in the order its ads first appear. */
export function adGroupParents(rows: readonly AdRow[]): ParentRow[] {
  return groupedByParent(rows, (row) => adGroupOf(row.change)).map(({ items, key, live }) => {
    const named = items.find((row) => row.adGroupName)
    return {
      cancelled: live.length === 0,
      context: named?.campaignName ?? null,
      key,
      name: named ? named.adGroupName : `Ad group ${items[0]?.change.adGroupId ?? ""}`,
      problems: live.filter((row) => row.problems.length > 0).length,
      values: { ads: live.length },
    }
  })
}
