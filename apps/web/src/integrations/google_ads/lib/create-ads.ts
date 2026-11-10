// apps/web/src/integrations/google_ads/lib/create-ads.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import {
  parseApprovalAccounts,
  type GoogleAdsApprovalAccount,
} from "@/integrations/google_ads/lib/accounts"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import { googleAdsId } from "@/integrations/google_ads/lib/field-values"
import { isRecord } from "@/lib/guards"

export const HEADLINE_LIMITS = { min: 3, max: 15, length: 30 } as const
export const DESCRIPTION_LIMITS = { min: 2, max: 4, length: 90 } as const
const PATH_LENGTH = 15

export const HEADLINE_PINS = ["HEADLINE_1", "HEADLINE_2", "HEADLINE_3"] as const
export const DESCRIPTION_PINS = ["DESCRIPTION_1", "DESCRIPTION_2"] as const

type AdStatus = "PAUSED" | "ENABLED"
export type TextAsset = { pin: string | null; text: string }

export type AdGroupTarget = {
  key: string
  label: string
  // The reference as received, so an edit keeps every field.
  reference: Record<string, unknown>
}

/** An ad's copy and links, shared by every card that creates ads. */
export type AdCopy = {
  descriptions: TextAsset[]
  finalUrl: string
  headlines: TextAsset[]
  mobileFinalUrl: string
  path1: string
  path2: string
}

export type DraftAd = AdCopy & {
  adGroups: AdGroupTarget[]
  // The ad as received, so an edit keeps fields this card doesn't show.
  entry: Record<string, unknown>
}

type AdGroupCheck = { campaignName: string | null; name: string; problem: string | null }
type GoogleProblem = { adGroup: string | null; message: string }

type AdsChecks =
  | { unavailable: true }
  | {
      unavailable: false
      adGroups: Map<string, AdGroupCheck>
      // Google's rejections, keyed by the copy that was checked.
      googleProblems: Map<string, GoogleProblem[]>
      requestProblems: string[]
    }

export type CreateAdsArgs = {
  accounts: Map<string, GoogleAdsApprovalAccount>
  ads: DraftAd[]
  checks: AdsChecks
  status: AdStatus
}

export type AdRow = {
  ad: DraftAd
  // The ad's position in the edited request, from zero.
  index: number
  problems: string[]
  // The same problems with the ad group each names; null for one with the whole ad.
  issues: AdProblem[]
}

type AdProblem = { adGroup: string | null; message: string }

const UNAVAILABLE =
  "Google Ads couldn't check these ads. Check again, or decline and ask the agent to prepare them again."
const URL_PATTERN = /^https?:\/\/\S+$/i

/** Counts characters as Google does for Latin text, one per code point. */
export function characterCount(text: string): number {
  return Array.from(text).length
}

function text(value: unknown): string {
  return typeof value === "string" ? value : ""
}

function parseAssets(value: unknown): TextAsset[] | null {
  if (!Array.isArray(value)) return null
  const assets: TextAsset[] = []
  for (const item of value) {
    if (!isRecord(item) || typeof item["text"] !== "string") return null
    assets.push({ pin: typeof item["pin"] === "string" ? item["pin"] : null, text: item["text"] })
  }
  return assets
}

export function parseAdGroup(value: unknown): AdGroupTarget | null {
  if (!isRecord(value)) return null
  const customerId = googleAdsId(value["customer_id"])
  const adGroupId = googleAdsId(value["ad_group_id"])
  if (customerId === null || adGroupId === null) return null
  const label = text(value["label"]).trim()
  return {
    key: `customers/${customerId}/adGroups/${adGroupId}`,
    label: label || `Ad group ${adGroupId}`,
    reference: value,
  }
}

export function parseCopy(value: unknown): AdCopy | null {
  if (!isRecord(value)) return null
  const headlines = parseAssets(value["headlines"])
  const descriptions = parseAssets(value["descriptions"])
  if (headlines === null || descriptions === null) return null
  return {
    descriptions,
    finalUrl: text(value["final_url"]),
    headlines,
    mobileFinalUrl: text(value["mobile_final_url"]),
    path1: text(value["path1"]),
    path2: text(value["path2"]),
  }
}

function parseAd(value: unknown): DraftAd | null {
  const copy = parseCopy(value)
  if (copy === null || !isRecord(value) || !Array.isArray(value["ad_groups"])) return null
  const adGroups: AdGroupTarget[] = []
  for (const item of value["ad_groups"]) {
    const target = parseAdGroup(item)
    if (target === null) return null
    adGroups.push(target)
  }
  return { ...copy, adGroups, entry: value }
}

/** Identifies an ad's copy, so a check made on that copy applies only while it is unchanged. */
export function copyKey(ad: AdCopy): string {
  const assets = (items: readonly TextAsset[]) => items.map((item) => [item.text.trim(), item.pin])
  return JSON.stringify([
    assets(ad.headlines),
    assets(ad.descriptions),
    ad.finalUrl.trim(),
    ad.mobileFinalUrl.trim(),
    ad.path1.trim(),
    ad.path2.trim(),
  ])
}

function parseChecks(value: unknown): AdsChecks {
  if (!isRecord(value) || value["unavailable"] !== false) return { unavailable: true }
  const adGroups = new Map<string, AdGroupCheck>()
  if (isRecord(value["ad_groups"])) {
    for (const [key, check] of Object.entries(value["ad_groups"])) {
      if (!isRecord(check)) continue
      adGroups.set(key, {
        campaignName: text(check["campaign_name"]) || null,
        name: text(check["name"]) || key,
        problem: text(check["problem"]) || null,
      })
    }
  }
  const googleProblems = new Map<string, GoogleProblem[]>()
  for (const item of Array.isArray(value["ads"]) ? value["ads"] : []) {
    const copy = isRecord(item) ? parseCopy(item["ad"]) : null
    if (copy === null || !isRecord(item) || !Array.isArray(item["problems"])) continue
    const problems = item["problems"].flatMap((problem): GoogleProblem[] =>
      isRecord(problem) && typeof problem["message"] === "string"
        ? [{ adGroup: text(problem["ad_group"]) || null, message: problem["message"] }]
        : []
    )
    const key = copyKey(copy)
    // Two ads with the same copy get the same problems, which the card shows once.
    const merged = [...(googleProblems.get(key) ?? []), ...problems]
    googleProblems.set(key, [
      ...new Map(
        merged.map((problem) => [`${String(problem.adGroup)}|${problem.message}`, problem])
      ).values(),
    ])
  }
  const requestProblems = Array.isArray(value["problems"])
    ? value["problems"].filter((item): item is string => typeof item === "string")
    : []
  return { unavailable: false, adGroups, googleProblems, requestProblems }
}

/** Reads `ads` and `status` with the trusted `_accounts` and `_checks`; null when malformed. */
export function parseCreateAdsArgs(value: unknown): CreateAdsArgs | null {
  if (!isRecord(value) || !Array.isArray(value["ads"])) return null
  const ads: DraftAd[] = []
  for (const item of value["ads"]) {
    const ad = parseAd(item)
    if (ad === null) return null
    ads.push(ad)
  }
  const status = value["status"] ?? "PAUSED"
  if (status !== "PAUSED" && status !== "ENABLED") return null
  return {
    accounts: parseApprovalAccounts(value["_accounts"]),
    ads,
    checks: parseChecks(value["_checks"]),
    status,
  }
}

function assetProblems(
  noun: "Headline" | "Description",
  assets: readonly TextAsset[],
  limits: { min: number; max: number; length: number }
): string[] {
  const plural = `${noun.toLowerCase()}s`
  const problems: string[] = []
  if (assets.length < limits.min)
    problems.push(
      `Add at least ${String(limits.min)} ${plural}. This ad has ${String(assets.length)}.`
    )
  if (assets.length > limits.max)
    problems.push(`An ad can have at most ${String(limits.max)} ${plural}.`)
  assets.forEach((asset, index) => {
    const count = characterCount(asset.text.trim())
    if (count === 0) problems.push(`${noun} ${String(index + 1)} is empty.`)
    if (count > limits.length)
      problems.push(
        `${noun} ${String(index + 1)} is ${String(count)} characters. The limit is ${String(limits.length)}.`
      )
  })
  const texts = assets.map((asset) => asset.text.trim()).filter(Boolean)
  if (new Set(texts).size !== texts.length)
    problems.push(`Each ${noun.toLowerCase()} must be different.`)
  return problems
}

function linkProblems(ad: AdCopy): string[] {
  const problems: string[] = []
  if (!URL_PATTERN.test(ad.finalUrl.trim()))
    problems.push("Enter a final URL starting with http:// or https://.")
  if (ad.mobileFinalUrl.trim() && !URL_PATTERN.test(ad.mobileFinalUrl.trim()))
    problems.push("Enter a mobile URL starting with http:// or https://, or clear it.")
  for (const [label, path] of [
    ["Path 1", ad.path1],
    ["Path 2", ad.path2],
  ] as const) {
    const count = characterCount(path.trim())
    if (count > PATH_LENGTH)
      problems.push(`${label} is ${String(count)} characters. The limit is ${String(PATH_LENGTH)}.`)
  }
  if (ad.path2.trim() && !ad.path1.trim()) problems.push("Fill in path 1 before path 2.")
  return problems
}

/** What the card itself can tell is wrong with an ad's copy and links. */
export function adCopyProblems(ad: AdCopy): string[] {
  return [
    ...assetProblems("Headline", ad.headlines, HEADLINE_LIMITS),
    ...assetProblems("Description", ad.descriptions, DESCRIPTION_LIMITS),
    ...linkProblems(ad),
  ]
}

/** What the card can find without asking Google again, so these block a check. */
function cardProblems(ad: DraftAd, checks: AdsChecks): AdProblem[] {
  const problems = adCopyProblems(ad).map((message): AdProblem => ({ adGroup: null, message }))
  if (ad.adGroups.length === 0)
    problems.push({ adGroup: null, message: "Choose at least one ad group." })
  if (checks.unavailable) return problems
  for (const group of ad.adGroups) {
    const problem = checks.adGroups.get(group.key)?.problem
    if (problem)
      problems.push({ adGroup: group.key, message: `${adGroupName(group, checks)}: ${problem}` })
  }
  return problems
}

/** Everything that blocks this ad, from the card's own checks and Google's dry run. */
function adProblems(ad: DraftAd, checks: AdsChecks): AdProblem[] {
  const problems = cardProblems(ad, checks)
  if (checks.unavailable) return [...problems, { adGroup: null, message: UNAVAILABLE }]
  // Google checked this exact copy, so its rejections stop applying once the copy changes.
  for (const problem of checks.googleProblems.get(copyKey(ad)) ?? []) {
    const group = ad.adGroups.find((item) => item.key === problem.adGroup)
    if (problem.adGroup !== null && !group) continue
    problems.push({
      adGroup: problem.adGroup,
      message: group ? `${adGroupName(group, checks)}: ${problem.message}` : problem.message,
    })
  }
  return problems
}

export function adGroupName(group: AdGroupTarget, checks: AdsChecks): string {
  return (checks.unavailable ? null : checks.adGroups.get(group.key)?.name) ?? group.label
}

export function adRows(args: CreateAdsArgs): AdRow[] {
  return args.ads.map((ad, index) => {
    const problems = adProblems(ad, args.checks)
    return { ad, index, issues: problems, problems: problems.map((problem) => problem.message) }
  })
}

/** The problems that stop this ad in one ad group, so cancelling it there clears them. */
export function problemsIn(row: AdRow, key: string): string[] {
  return row.issues
    .filter((issue) => issue.adGroup === null || issue.adGroup === key)
    .map((issue) => issue.message)
}

export type CreateAdsCounts = { adGroups: number; ads: number; problems: number; writes: number }

export function createAdsCounts(rows: readonly AdRow[]): CreateAdsCounts {
  return {
    adGroups: new Set(rows.flatMap((row) => row.ad.adGroups.map((group) => group.key))).size,
    ads: rows.length,
    problems: rows.filter((row) => row.problems.length > 0).length,
    // Each ad is created once per ad group.
    writes: rows.reduce((total, row) => total + row.ad.adGroups.length, 0),
  }
}

/** Google's problems with the whole request rather than one ad. */
export function adsRequestProblems(args: CreateAdsArgs): string[] {
  return args.checks.unavailable ? [] : args.checks.requestProblems
}

/** True when Google hasn't answered for this request. Status doesn't change its answer. */
export function adsNeedCheck(args: CreateAdsArgs, checked: CreateAdsArgs): boolean {
  return (
    args.checks.unavailable ||
    JSON.stringify(serializeAds(args.ads)) !== JSON.stringify(serializeAds(checked.ads))
  )
}

export function canCheckAds(args: CreateAdsArgs): boolean {
  return args.ads.length > 0 && args.ads.every((ad) => cardProblems(ad, args.checks).length === 0)
}

/** Why the request can't be approved yet, or null. */
export function createAdsBlock(args: CreateAdsArgs | null, checked: CreateAdsArgs): string | null {
  if (args === null) return null
  const counts = createAdsCounts(adRows(args))
  if (counts.ads === 0) return "Every ad is cancelled. Decline this request, or restore one."
  const [problem] = adsRequestProblems(args)
  if (problem) return problem
  if (counts.problems > 0)
    return `Fix or cancel ${approvalCountLine(counts.problems, "ad")} to continue.`
  return adsNeedCheck(args, checked)
    ? "Click Check Changes so Google can check your edits, then approve."
    : null
}

export function createAdsPrompt(args: CreateAdsArgs): string {
  const counts = createAdsCounts(adRows(args))
  if (counts.ads === 0) return "Nothing is left to create."
  const account = args.accounts.values().next().value?.label ?? "Google Ads"
  return `Create ${approvalCountLine(counts.writes, "responsive search ad")} in ${approvalCountLine(counts.adGroups, "ad group")} in ${account}.`
}

export function createAdsApproveLabel(args: CreateAdsArgs): string {
  const { writes } = createAdsCounts(adRows(args))
  return writes === 0 ? "Create Ads" : `Create ${String(writes)} ${writes === 1 ? "Ad" : "Ads"}`
}

export function createAdsDetails(args: CreateAdsArgs | null): FanOutDetail[] {
  if (args === null) return []
  const counts = createAdsCounts(adRows(args))
  return [
    { label: "Ads", value: String(counts.writes) },
    { label: "Ad Groups", value: String(counts.adGroups) },
    { label: "Status", value: args.status === "ENABLED" ? "Launch" : "Paused" },
  ]
}

/** An ad's copy and links as the tool takes them; blank optional fields are null. */
export function serializeCopy(ad: AdCopy): Record<string, unknown> {
  const assets = (items: readonly TextAsset[]) =>
    items.map((item) => (item.pin ? { text: item.text, pin: item.pin } : { text: item.text }))
  return {
    headlines: assets(ad.headlines),
    descriptions: assets(ad.descriptions),
    final_url: ad.finalUrl,
    mobile_final_url: ad.mobileFinalUrl.trim() ? ad.mobileFinalUrl : null,
    path1: ad.path1.trim() ? ad.path1 : null,
    path2: ad.path2.trim() ? ad.path2 : null,
  }
}

/** What the card keeps beside the request: cancelled ads for Undo, and ad groups with no ads yet. */
export type CreateAdsRetained = { adGroups: AdGroupTarget[]; ads: DraftAd[] }

/** Each ad's ad groups already in the request, keyed by the ad's copy. */
function groupsByCopy(ads: readonly DraftAd[]): Map<string, Set<string>> {
  const byCopy = new Map<string, Set<string>>()
  for (const ad of ads) {
    const groups = byCopy.get(copyKey(ad)) ?? new Set<string>()
    for (const group of ad.adGroups) groups.add(group.key)
    byCopy.set(copyKey(ad), groups)
  }
  return byCopy
}

/** Reads what the card retained. A reset of the card's edits can return it to the request. */
export function parseRetained(value: unknown, args: CreateAdsArgs): CreateAdsRetained {
  if (!isRecord(value)) return { adGroups: [], ads: [] }
  const current = groupsByCopy(args.ads)
  const ads = (Array.isArray(value["ads"]) ? value["ads"] : []).flatMap((item) => {
    const ad = parseAd(item)
    if (ad === null) return []
    const inRequest = current.get(copyKey(ad))
    const adGroups = ad.adGroups.filter((group) => !inRequest?.has(group.key))
    return adGroups.length > 0 ? [{ ...ad, adGroups }] : []
  })
  const used = new Set([...args.ads, ...ads].flatMap((ad) => ad.adGroups.map((group) => group.key)))
  const adGroups = (Array.isArray(value["ad_groups"]) ? value["ad_groups"] : []).flatMap((item) => {
    const group = parseAdGroup(item)
    return group && !used.has(group.key) ? [group] : []
  })
  return { adGroups, ads }
}

export function serializeRetained(retained: CreateAdsRetained): Record<string, unknown> {
  return {
    ad_groups: retained.adGroups.map((group) => group.reference),
    ads: serializeAds(retained.ads),
  }
}

type AdsEdit = { ads: DraftAd[]; retained: CreateAdsRetained }

/** Takes each ad out of the ad groups `take` names, keeping what was taken for Undo. */
export function cancelInAdGroups(
  ads: readonly DraftAd[],
  retained: CreateAdsRetained,
  take: (ad: DraftAd, index: number) => ReadonlySet<string>
): AdsEdit {
  const kept: DraftAd[] = []
  const cancelled = [...retained.ads]
  ads.forEach((ad, index) => {
    const taken = take(ad, index)
    const out = ad.adGroups.filter((group) => taken.has(group.key))
    const rest = ad.adGroups.filter((group) => !taken.has(group.key))
    if (out.length > 0) cancelled.push({ ...ad, adGroups: out })
    if (rest.length > 0) kept.push({ ...ad, adGroups: rest })
  })
  return { ads: kept, retained: { ...retained, ads: cancelled } }
}

/** Puts cancelled ads back in one ad group, or in all of them, joining an ad with the same copy. */
export function restoreAdGroups(
  ads: readonly DraftAd[],
  retained: CreateAdsRetained,
  key: string | null
): AdsEdit {
  const restored = ads.map((ad) => ({ ...ad, adGroups: [...ad.adGroups] }))
  const cancelled: DraftAd[] = []
  for (const ad of retained.ads) {
    const back = ad.adGroups.filter((group) => key === null || group.key === key)
    const rest = ad.adGroups.filter((group) => key !== null && group.key !== key)
    if (rest.length > 0) cancelled.push({ ...ad, adGroups: rest })
    if (back.length === 0) continue
    const same = restored.find((item) => copyKey(item) === copyKey(ad))
    if (!same) {
      restored.push({ ...ad, adGroups: back })
      continue
    }
    const known = new Set(same.adGroups.map((group) => group.key))
    same.adGroups.push(...back.filter((group) => !known.has(group.key)))
  }
  return { ads: restored, retained: { ...retained, ads: cancelled } }
}

export type AdGroupParent = {
  // Positions of the request's ads in this ad group.
  ads: number[]
  campaignName: string | null
  // Ads cancelled in this ad group, for Undo.
  cancelled: number
  name: string
  problems: number
  // A cancelled ad group has no ads left in the request; a new one hasn't had any yet.
  state: "live" | "cancelled" | "new"
  target: AdGroupTarget
}

/** The ad groups the ads go in, in request order, then cancelled ones, then new ones. */
export function adGroupParents(
  args: CreateAdsArgs,
  rows: readonly AdRow[],
  retained: CreateAdsRetained
): AdGroupParent[] {
  const parents = new Map<string, AdGroupParent>()
  const parent = (target: AdGroupTarget, state: AdGroupParent["state"]) => {
    const found = parents.get(target.key)
    if (found) return found
    const check = args.checks.unavailable ? undefined : args.checks.adGroups.get(target.key)
    const made: AdGroupParent = {
      ads: [],
      campaignName: check?.campaignName ?? null,
      cancelled: 0,
      name: adGroupName(target, args.checks),
      problems: 0,
      state,
      target,
    }
    parents.set(target.key, made)
    return made
  }
  for (const row of rows) {
    for (const group of row.ad.adGroups) {
      const item = parent(group, "live")
      item.ads.push(row.index)
      if (problemsIn(row, group.key).length > 0) item.problems += 1
    }
  }
  for (const ad of retained.ads)
    for (const group of ad.adGroups) parent(group, "cancelled").cancelled += 1
  for (const group of retained.adGroups) parent(group, "new")
  return [...parents.values()]
}

/** The `ads` value for the given drafts, keeping each entry's other fields. */
export function serializeAds(ads: readonly DraftAd[]): Record<string, unknown>[] {
  return ads.map((ad) => ({
    ...ad.entry,
    ...serializeCopy(ad),
    ad_groups: ad.adGroups.map((group) => group.reference),
  }))
}

/** The value every ad shares for these fields, or null when they differ. */
export function sharedValue<K extends keyof DraftAd>(
  ads: readonly DraftAd[],
  field: K
): DraftAd[K] | null {
  const first = ads[0]
  if (first === undefined) return null
  return ads.every((ad) => ad[field] === first[field]) ? first[field] : null
}

/** The site name and URL Google shows above the headline: the host, then the display paths. */
export function previewSite(ad: Pick<AdCopy, "finalUrl" | "path1" | "path2">): {
  name: string
  url: string
} {
  const paths = [ad.path1.trim(), ad.path2.trim()].filter(Boolean)
  try {
    const { host, protocol } = new URL(ad.finalUrl.trim())
    return { name: host.replace(/^www\./, ""), url: [`${protocol}//${host}`, ...paths].join("/") }
  } catch {
    return { name: "Your site", url: [ad.finalUrl.trim(), ...paths].filter(Boolean).join("/") }
  }
}

/** The headlines and descriptions shown first: pinned ones in their place, then the rest in order. */
export function previewAssets(assets: readonly TextAsset[], pins: readonly string[]): string[] {
  const shown: (string | null)[] = pins.map(
    (pin) => assets.find((asset) => asset.pin === pin)?.text.trim() ?? null
  )
  const rest = assets
    .filter((asset) => asset.pin === null && asset.text.trim())
    .map((asset) => asset.text.trim())
  return shown.map((value) => value ?? rest.shift() ?? null).filter((value) => value !== null)
}
