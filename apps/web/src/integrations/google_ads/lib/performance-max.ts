// apps/web/src/integrations/google_ads/lib/performance-max.ts

import type { EntityChoice } from "@/features/tools/types"
import { parseEach, text } from "@/integrations/google_ads/lib/create-ad-groups"
import { characterCount } from "@/integrations/google_ads/lib/create-ads"
import { googleAdsId, isGoogleAdsUrl } from "@/integrations/google_ads/lib/field-values"
import { isRecord } from "@/lib/guards"

const MAX_ASSET_GROUPS = 5
const MAX_SEARCH_THEMES = 25
export const MAX_AUDIENCE_SIGNALS = 20
const MAX_LOGOS = 5
const SHORT_DESCRIPTION = 60
const BUSINESS_NAME_LENGTH = 25
const SEARCH_THEME_LENGTH = 80

export const IMAGE_TYPES = [
  "MARKETING_IMAGE",
  "SQUARE_MARKETING_IMAGE",
  "PORTRAIT_MARKETING_IMAGE",
] as const
export type ImageType = (typeof IMAGE_TYPES)[number]
export const LOGO_TYPES = ["LOGO", "LANDSCAPE_LOGO"] as const
export type LogoType = (typeof LOGO_TYPES)[number]

export const IMAGE_TYPE_LABELS: Record<ImageType | LogoType, string> = {
  LANDSCAPE_LOGO: "Landscape logo",
  LOGO: "Square logo",
  MARKETING_IMAGE: "Landscape",
  PORTRAIT_MARKETING_IMAGE: "Portrait",
  SQUARE_MARKETING_IMAGE: "Square",
}

export type TextKind = "headlines" | "longHeadlines" | "descriptions"

// Google's minimum, maximum, and length of each text type in one asset group.
export const TEXT_LIMITS: Record<TextKind, { min: number; max: number; length: number }> = {
  descriptions: { min: 2, max: 5, length: 90 },
  headlines: { min: 3, max: 15, length: 30 },
  longHeadlines: { min: 1, max: 5, length: 90 },
}

export const SEARCH_THEME_LIMITS = { min: 0, max: MAX_SEARCH_THEMES, length: SEARCH_THEME_LENGTH }

const TEXT_NOUNS: Record<TextKind, string> = {
  descriptions: "description",
  headlines: "headline",
  longHeadlines: "long headline",
}

// Google's minimum and maximum of each image shape in one asset group.
export const IMAGE_LIMITS: Record<ImageType, { min: number; max: number }> = {
  MARKETING_IMAGE: { min: 1, max: 20 },
  PORTRAIT_MARKETING_IMAGE: { min: 0, max: 20 },
  SQUARE_MARKETING_IMAGE: { min: 1, max: 20 },
}

/** An image asset already in the account, and the shape it shows as. */
export type DraftImage<T extends string = ImageType> = {
  assetId: string
  fieldType: T
  label: string
  // The reference as received, so an edit keeps every field.
  reference: Record<string, unknown>
}

const SIGNAL_AUDIENCE_KINDS = ["user_list", "user_interest", "custom_audience"] as const
type SignalAudienceKind = (typeof SIGNAL_AUDIENCE_KINDS)[number]

/** An audience that guides Google; the group's signals read as people in any of them. */
export type DraftAudienceSignal = { key: string; kind: SignalAudienceKind; name: string }

export type DraftAssetGroup = {
  audienceSignals: DraftAudienceSignal[]
  descriptions: string[]
  finalUrl: string
  headlines: string[]
  images: DraftImage[]
  longHeadlines: string[]
  name: string
  searchThemes: string[]
  // YouTube video references, as received.
  videos: Record<string, unknown>[]
}

type DraftGoal = { category: string; origin: string }

export type DraftPerformanceMax = {
  businessName: string
  // Null bids for the account's goals.
  conversionGoals: DraftGoal[] | null
  finalUrlExpansion: boolean
  languages: { key: string; name: string }[]
  logos: DraftImage<LogoType>[]
  merchant: { feedLabel: string; merchantId: string } | null
}

type ImageFacts = { fits: string[]; height: number; name: string; width: number }

type AccountGoal = DraftGoal & { biddable: boolean; name: string }

type GroupProblem = {
  assetGroup: string
  content: string | null
  kind: string
  message: string
}

/** What Google told the card about a Performance Max campaign. */
export type PerformanceMaxChecks = {
  accountGoals: AccountGoal[]
  // Google's name for each audience signal, by `kind:key`.
  audiences: Map<string, string>
  groupProblems: GroupProblem[]
  images: Map<string, ImageFacts>
  languageNames: Map<string, string>
  merchantIds: string[]
  unknownAudiences: Set<string>
  unknownImages: Set<string>
  unknownLanguages: Set<string>
}

export type AssetGroupRow = { group: DraftAssetGroup; index: number; problems: string[] }

function strings(value: unknown): string[] | null {
  if (value === undefined || value === null) return []
  if (!Array.isArray(value)) return null
  return value.every((item) => typeof item === "string") ? value : null
}

function parseImage<T extends string>(
  value: unknown,
  types: readonly T[],
  fallback: T | null
): DraftImage<T> | null {
  if (!isRecord(value) || !isRecord(value["asset"])) return null
  const reference = value["asset"]
  const assetId = googleAdsId(reference["asset_id"])
  const fieldType = value["field_type"] ?? fallback
  if (assetId === null || !types.includes(fieldType as T)) return null
  return {
    assetId,
    fieldType: fieldType as T,
    label: text(reference["label"]).trim() || `Image ${assetId}`,
    reference,
  }
}

export function audienceSignalId(signal: { key: string; kind: string }): string {
  return `${signal.kind}:${signal.key}`
}

/** An audience signal from the request or an audience search result; null when it can't be one. */
export function parseAudienceSignal(value: unknown): DraftAudienceSignal | null {
  if (!isRecord(value)) return null
  const kind = value["kind"]
  const key = googleAdsId(value["key"])
  if (key === null || !SIGNAL_AUDIENCE_KINDS.includes(kind as SignalAudienceKind)) return null
  return { key, kind: kind as SignalAudienceKind, name: text(value["name"]) }
}

export function parseAssetGroup(value: unknown): DraftAssetGroup | null {
  if (!isRecord(value) || typeof value["name"] !== "string") return null
  const headlines = strings(value["headlines"])
  const longHeadlines = strings(value["long_headlines"])
  const descriptions = strings(value["descriptions"])
  const searchThemes = strings(value["search_themes"])
  const images = parseEach(value["images"], (item) => parseImage(item, IMAGE_TYPES, null))
  const videos = parseEach(value["videos"], (item) => (isRecord(item) ? item : null))
  const audienceSignals = parseEach(value["audience_signals"] ?? [], parseAudienceSignal)
  if (!headlines || !longHeadlines || !descriptions || !searchThemes || !images || !videos)
    return null
  if (!audienceSignals) return null
  return {
    audienceSignals,
    descriptions,
    finalUrl: text(value["final_url"]),
    headlines,
    images,
    longHeadlines,
    name: value["name"],
    searchThemes,
    videos,
  }
}

function parseGoal(value: unknown): DraftGoal | null {
  if (!isRecord(value)) return null
  const { category, origin } = value
  return typeof category === "string" && typeof origin === "string" ? { category, origin } : null
}

function parseLanguage(value: unknown): { key: string; name: string } | null {
  if (!isRecord(value) || typeof value["key"] !== "string" || !/^\d+$/.test(value["key"]))
    return null
  return { key: value["key"], name: text(value["name"]) }
}

/** Reads the Performance Max fields of a campaign; null when malformed. */
export function parsePerformanceMax(value: Record<string, unknown>): DraftPerformanceMax | null {
  const languages = parseEach(value["languages"], parseLanguage)
  const logos = parseEach(value["logos"], (item) => parseImage(item, LOGO_TYPES, "LOGO"))
  const goals = value["conversion_goals"]
  const conversionGoals = goals === undefined || goals === null ? null : parseEach(goals, parseGoal)
  const merchant = value["merchant"]
  if (languages === null || logos === null) return null
  if (goals !== undefined && goals !== null && conversionGoals === null) return null
  if (merchant !== undefined && merchant !== null && !isRecord(merchant)) return null
  return {
    businessName: text(value["business_name"]),
    conversionGoals,
    finalUrlExpansion: value["final_url_expansion"] !== false,
    languages,
    logos,
    merchant: isRecord(merchant)
      ? { feedLabel: text(merchant["feed_label"]), merchantId: text(merchant["merchant_id"]) }
      : null,
  }
}

function parseGroupProblems(value: unknown): GroupProblem[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item): GroupProblem[] =>
    isRecord(item) && typeof item["message"] === "string"
      ? [
          {
            assetGroup: text(item["asset_group"]),
            content: text(item["content"]) || null,
            kind: text(item["kind"]),
            message: item["message"],
          },
        ]
      : []
  )
}

function parseImageFacts(value: unknown): Map<string, ImageFacts> {
  if (!isRecord(value)) return new Map()
  return new Map(
    Object.entries(value).flatMap(([assetId, facts]) =>
      isRecord(facts) && typeof facts["width"] === "number" && typeof facts["height"] === "number"
        ? [
            [
              assetId,
              {
                fits: strings(facts["fits"]) ?? [],
                height: facts["height"],
                name: text(facts["name"]),
                width: facts["width"],
              },
            ] as const,
          ]
        : []
    )
  )
}

/** Reads the Performance Max part of the trusted `_checks`. */
export function parsePerformanceMaxChecks(value: Record<string, unknown>): PerformanceMaxChecks {
  const names = isRecord(value["languages"]) ? value["languages"] : {}
  const goals = Array.isArray(value["account_goals"]) ? value["account_goals"] : []
  const audiences = isRecord(value["audiences"]) ? value["audiences"] : {}
  return {
    accountGoals: goals.flatMap((item): AccountGoal[] => {
      const goal = parseGoal(item)
      return goal && isRecord(item)
        ? [{ ...goal, biddable: item["biddable"] === true, name: text(item["name"]) }]
        : []
    }),
    audiences: new Map(
      Object.entries(audiences).flatMap(([id, name]) =>
        typeof name === "string" ? [[id, name] as const] : []
      )
    ),
    groupProblems: parseGroupProblems(value["problems"]),
    images: parseImageFacts(value["images"]),
    languageNames: new Map(
      Object.entries(names).flatMap(([key, name]) =>
        typeof name === "string" ? [[key, name] as const] : []
      )
    ),
    merchantIds: strings(value["merchant_ids"]) ?? [],
    unknownAudiences: new Set(strings(value["unknown_audiences"]) ?? []),
    unknownImages: new Set(strings(value["unknown_images"]) ?? []),
    unknownLanguages: new Set(strings(value["unknown_languages"]) ?? []),
  }
}

function imageValue(image: DraftImage<string>): Record<string, unknown> {
  return { asset: image.reference, field_type: image.fieldType }
}

/** The asset group's argument value; blank text lines are left out. */
function serializeAssetGroup(group: DraftAssetGroup): Record<string, unknown> {
  const lines = (items: readonly string[]) => items.map((item) => item.trim()).filter(Boolean)
  return {
    name: group.name,
    final_url: group.finalUrl.trim(),
    headlines: lines(group.headlines),
    long_headlines: lines(group.longHeadlines),
    descriptions: lines(group.descriptions),
    images: group.images.map(imageValue),
    videos: group.videos,
    search_themes: lines(group.searchThemes),
    audience_signals: group.audienceSignals.map((signal) => ({
      kind: signal.kind,
      key: signal.key,
      name: signal.name || null,
    })),
  }
}

export function serializeAssetGroups(
  groups: readonly DraftAssetGroup[]
): Record<string, unknown>[] {
  return groups.map(serializeAssetGroup)
}

/** The campaign's Performance Max fields, beside the settings every campaign shares. */
export function serializePerformanceMax(fields: DraftPerformanceMax): Record<string, unknown> {
  return {
    type: "performance_max",
    languages: fields.languages.map((item) => ({ key: item.key, name: item.name || null })),
    // Sent as typed, so a space typed mid-name survives; the server tidies it.
    business_name: fields.businessName || null,
    logos: fields.logos.map(imageValue),
    final_url_expansion: fields.finalUrlExpansion,
    conversion_goals: fields.conversionGoals,
    merchant: fields.merchant
      ? {
          merchant_id: fields.merchant.merchantId.trim(),
          feed_label: fields.merchant.feedLabel || null,
        }
      : null,
  }
}

export function parseCancelledAssetGroups(
  value: unknown,
  groups: readonly DraftAssetGroup[]
): DraftAssetGroup[] {
  const current = new Set(groups.map((group) => JSON.stringify(serializeAssetGroup(group))))
  return (parseEach(value, parseAssetGroup) ?? []).filter(
    (group) => !current.has(JSON.stringify(serializeAssetGroup(group)))
  )
}

export function textLines(items: readonly string[]): string[] {
  return items.map((item) => item.trim()).filter(Boolean)
}

export function imageCount(group: DraftAssetGroup, fieldType: ImageType): number {
  return group.images.filter((image) => image.fieldType === fieldType).length
}

/** True when the group links none of its own assets, so a retail campaign fills it from the feed. */
export function isBare(group: DraftAssetGroup): boolean {
  return (
    textLines(group.headlines).length === 0 &&
    textLines(group.longHeadlines).length === 0 &&
    textLines(group.descriptions).length === 0 &&
    group.images.length === 0 &&
    group.videos.length === 0
  )
}

function textProblems(group: DraftAssetGroup, kind: TextKind, retailBare: boolean): string[] {
  const items = textLines(group[kind])
  const { length, max, min } = TEXT_LIMITS[kind]
  const noun = TEXT_NOUNS[kind]
  const problems: string[] = []
  if (!retailBare && items.length < min)
    problems.push(`Needs at least ${String(min)} ${noun}s, has ${String(items.length)}.`)
  if (items.length > max) problems.push(`Takes at most ${String(max)} ${noun}s.`)
  if (items.some((item) => characterCount(item) > length))
    problems.push(`A ${noun} is over ${String(length)} characters.`)
  if (new Set(items).size !== items.length) problems.push(`Each ${noun} must be different.`)
  return problems
}

/** Why an image can't show in its shape, from Google's read of its size; null when it fits. */
export function imageProblem(
  image: DraftImage<string>,
  checks: PerformanceMaxChecks | null
): string | null {
  if (checks === null) return null
  if (checks.unknownImages.has(image.assetId))
    return `${image.label} isn't an image in this account.`
  const facts = checks.images.get(image.assetId)
  if (facts && !facts.fits.includes(image.fieldType)) {
    const shape = IMAGE_TYPE_LABELS[image.fieldType as ImageType | LogoType].toLowerCase()
    return `${image.label} (${String(facts.width)} by ${String(facts.height)}) doesn't fit the ${shape} shape.`
  }
  return null
}

function imageProblems(
  group: DraftAssetGroup,
  checks: PerformanceMaxChecks | null,
  retailBare: boolean
): string[] {
  const problems: string[] = []
  for (const fieldType of IMAGE_TYPES) {
    const count = imageCount(group, fieldType)
    const { max, min } = IMAGE_LIMITS[fieldType]
    const shape = IMAGE_TYPE_LABELS[fieldType].toLowerCase()
    if (!retailBare && count < min) problems.push(`Needs at least ${String(min)} ${shape} image.`)
    if (count > max) problems.push(`Takes at most ${String(max)} ${shape} images.`)
  }
  for (const image of group.images) {
    const problem = imageProblem(image, checks)
    if (problem) problems.push(problem)
  }
  return problems
}

export function audienceSignalName(
  signal: DraftAudienceSignal,
  checks: PerformanceMaxChecks | null
): string {
  return checks?.audiences.get(audienceSignalId(signal)) ?? (signal.name || signal.key)
}

function audienceProblems(group: DraftAssetGroup, checks: PerformanceMaxChecks | null): string[] {
  const problems: string[] = []
  if (group.audienceSignals.length > MAX_AUDIENCE_SIGNALS)
    problems.push(`Takes at most ${String(MAX_AUDIENCE_SIGNALS)} audiences in its signal.`)
  for (const signal of group.audienceSignals) {
    if (checks?.unknownAudiences.has(audienceSignalId(signal)))
      problems.push(`${signal.name || signal.key} isn't an audience in this account. Remove it.`)
  }
  return problems
}

const SIGNAL_KINDS = new Set(["audience", "audience_signal"])

/** Google's dry run answers for the group, while what it rejected is still there. */
function googleGroupProblems(
  group: DraftAssetGroup,
  checks: PerformanceMaxChecks | null
): string[] {
  if (checks === null) return []
  const present = new Set([
    ...textLines(group.headlines),
    ...textLines(group.longHeadlines),
    ...textLines(group.descriptions),
    ...textLines(group.searchThemes),
    ...group.images.map((image) => image.assetId),
    ...group.videos.map((video) => video["asset_id"]),
  ])
  return checks.groupProblems
    .filter(
      (problem) =>
        problem.assetGroup === group.name &&
        (problem.content === null || present.has(problem.content)) &&
        (!SIGNAL_KINDS.has(problem.kind) || group.audienceSignals.length > 0)
    )
    .map((problem) =>
      problem.content ? `${problem.content}: ${problem.message}` : problem.message
    )
}

/** What Google needs before it accepts the group, as the server checks it, plus its answers. */
function assetGroupProblems(
  group: DraftAssetGroup,
  groups: readonly DraftAssetGroup[],
  { checks, retail }: { checks: PerformanceMaxChecks | null; retail: boolean }
): string[] {
  const retailBare = retail && isBare(group)
  const problems: string[] = []
  const name = group.name.trim()
  if (!name) problems.push("Give the asset group a name.")
  if (groups.filter((other) => other.name.trim().toLowerCase() === name.toLowerCase()).length > 1)
    problems.push("Give each asset group a different name.")
  if (!isGoogleAdsUrl(group.finalUrl.trim()))
    problems.push("Enter a final URL starting with http:// or https://.")
  for (const kind of ["headlines", "longHeadlines", "descriptions"] as const)
    problems.push(...textProblems(group, kind, retailBare))
  const descriptions = textLines(group.descriptions)
  if (
    descriptions.length > 0 &&
    descriptions.every((item) => characterCount(item) > SHORT_DESCRIPTION)
  )
    problems.push(`Needs one description of ${String(SHORT_DESCRIPTION)} characters or fewer.`)
  problems.push(...imageProblems(group, checks, retailBare))
  const themes = textLines(group.searchThemes)
  if (themes.length > MAX_SEARCH_THEMES)
    problems.push(`Takes at most ${String(MAX_SEARCH_THEMES)} search themes.`)
  if (themes.some((theme) => characterCount(theme) > SEARCH_THEME_LENGTH))
    problems.push(`A search theme is over ${String(SEARCH_THEME_LENGTH)} characters.`)
  return [...problems, ...audienceProblems(group, checks), ...googleGroupProblems(group, checks)]
}

export function assetGroupRows(
  groups: readonly DraftAssetGroup[],
  context: { checks: PerformanceMaxChecks | null; retail: boolean }
): AssetGroupRow[] {
  return groups.map((group, index) => ({
    group,
    index,
    problems: assetGroupProblems(group, groups, context),
  }))
}

/** What the brand, goals, feed, and languages need, as the server checks them. */
export function performanceMaxProblems(
  fields: DraftPerformanceMax,
  groups: readonly DraftAssetGroup[],
  checks: PerformanceMaxChecks | null
): string[] {
  const problems: string[] = []
  const name = fields.businessName.trim()
  const retailOnly = fields.merchant !== null && groups.every(isBare)
  if (!(retailOnly && !name && fields.logos.length === 0)) {
    if (!name) problems.push("Add the business name, as it should appear in the ads.")
    if (!fields.logos.some((logo) => logo.fieldType === "LOGO"))
      problems.push("Add at least one square logo.")
  }
  if (characterCount(name) > BUSINESS_NAME_LENGTH)
    problems.push(`The business name is over ${String(BUSINESS_NAME_LENGTH)} characters.`)
  if (fields.logos.length > MAX_LOGOS) problems.push(`Add at most ${String(MAX_LOGOS)} logos.`)
  for (const logo of fields.logos) {
    const problem = imageProblem(logo, checks)
    if (problem) problems.push(problem)
  }
  if (fields.conversionGoals?.length === 0)
    problems.push("Choose at least one conversion goal, or use the account's goals.")
  const merchant = fields.merchant
  if (merchant && !/^\d+$/.test(merchant.merchantId.trim()))
    problems.push("Enter the Merchant Center account ID as digits.")
  else if (merchant && checks && !checks.merchantIds.includes(merchant.merchantId.trim()))
    problems.push(
      `Merchant Center account ${merchant.merchantId.trim()} isn't linked to this Google Ads account. Link it in Google Ads, or leave the product feed out.`
    )
  for (const language of fields.languages) {
    if (checks?.unknownLanguages.has(language.key))
      problems.push(`Google doesn't recognise ${language.name || language.key}. Remove it.`)
  }
  return problems
}

export function goalsSummary(
  fields: DraftPerformanceMax,
  checks: PerformanceMaxChecks | null
): string {
  const goals = checks?.accountGoals ?? []
  if (fields.conversionGoals === null) {
    const bidding = goals.filter((goal) => goal.biddable).map((goal) => goal.name)
    return bidding.length > 0 ? `${bidding.join(", ")} · uses account goals` : "Uses account goals"
  }
  const names = fields.conversionGoals.map(
    (goal) =>
      goals.find((item) => item.category === goal.category && item.origin === goal.origin)?.name ??
      `${goal.category} from ${goal.origin}`.toLowerCase()
  )
  return names.length > 0 ? `${names.join(", ")} · this campaign only` : "No goals chosen"
}

export function brandSummary(fields: DraftPerformanceMax): string {
  const logos = fields.logos.length
  return [
    fields.businessName.trim() || "No business name",
    `${String(logos)} logo${logos === 1 ? "" : "s"}`,
    "brand guidelines on",
  ].join(" · ")
}

export function assetGroupsObjectCount(groups: readonly DraftAssetGroup[]): number {
  return groups.reduce(
    (sum, group) =>
      sum +
      2 +
      2 *
        (textLines(group.headlines).length +
          textLines(group.longHeadlines).length +
          textLines(group.descriptions).length) +
      group.images.length +
      group.videos.length +
      textLines(group.searchThemes).length +
      // One audience and one signal, however many audiences it holds.
      (group.audienceSignals.length > 0 ? 2 : 0),
    0
  )
}

export function blankAssetGroup(groups: readonly DraftAssetGroup[]): DraftAssetGroup | null {
  if (groups.length >= MAX_ASSET_GROUPS) return null
  const finalUrl = groups[0]?.finalUrl ?? ""
  return {
    audienceSignals: [],
    descriptions: [],
    finalUrl,
    headlines: [],
    images: [],
    longHeadlines: [],
    name: `Asset Group ${String(groups.length + 1)}`,
    searchThemes: [],
    videos: [],
  }
}

function choiceRatio(choice: EntityChoice): number | null {
  const match = /(\d+) by (\d+)/.exec(choice.description ?? "")
  return match ? Number(match[1]) / Number(match[2]) : null
}

/** Picks a shape for a new image from the size its search result shows. */
export function imageShapeFor(choice: EntityChoice): ImageType {
  const ratio = choiceRatio(choice)
  if (ratio !== null && Math.abs(ratio - 1) <= 0.01) return "SQUARE_MARKETING_IMAGE"
  if (ratio !== null && Math.abs(ratio - 0.8) <= 0.01) return "PORTRAIT_MARKETING_IMAGE"
  return "MARKETING_IMAGE"
}

export function logoShapeFor(choice: EntityChoice): LogoType {
  const ratio = choiceRatio(choice)
  return ratio !== null && ratio > 2 ? "LANDSCAPE_LOGO" : "LOGO"
}

/** An image search result as a draft image, or null when it isn't an image. */
export function imageFromChoice<T extends string>(
  choice: EntityChoice,
  fieldType: T
): DraftImage<T> | null {
  const assetId = googleAdsId(choice.value["asset_id"])
  if (assetId === null || choice.value["asset_type"] !== "IMAGE") return null
  return { assetId, fieldType, label: choice.label, reference: choice.value }
}
