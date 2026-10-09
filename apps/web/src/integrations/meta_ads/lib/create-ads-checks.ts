// apps/web/src/integrations/meta_ads/lib/create-ads-checks.ts

import { fieldOptionLabel } from "@/components/tool-ui/field-options"
import { hasAiGeneratedChange } from "@/integrations/meta_ads/lib/automatic-changes"
import { allowedButtons, DEFAULT_BUTTON } from "@/integrations/meta_ads/lib/call-to-action"
import {
  adSetName,
  MAX_CARDS,
  MIN_CARDS,
  RECOMMENDED_LENGTHS,
  type AdDraft,
  type AdSetInfo,
  type AdStatus,
  type Card,
  type CreateAdsArgs,
  type PreviewMedia,
} from "@/integrations/meta_ads/lib/create-ads-args"
import { formatCurrencyAmount, pluralize } from "@/lib/format"

type CheckLevel = "error" | "warning"
// The editor field a check belongs to, so its message shows beside that field.
export type CheckField =
  | "name"
  | "primary_text"
  | "headline"
  | "description"
  | "link"
  | "url_tags"
  | "call_to_action"
  | "media"
  | "cards"
export type AdCheck = { level: CheckLevel; message: string; field: CheckField }
export type RowCheck = "ready" | "warning" | "error"

export type AdRow = {
  ad: AdDraft
  link: string | null
  callToAction: string
  urlTags: string | null
  status: AdStatus
  // True when an AI-generated change makes this ad start off whatever its status says.
  statusForced: boolean
  allowedButtons: string[]
  checks: AdCheck[]
  check: RowCheck
}

const PRIMARY_TEXT_LIMIT = 2200
const NAME_LIMIT = 200
const HASHTAG_LIMIT = 30
// Matches the server's count: a # that doesn't follow a letter, digit, or another #.
const HASHTAG_PATTERN = /(?<![\p{L}\p{N}_#])#[\p{L}\p{N}_]/gu
const TEXT_LIMIT = 255
const URL_TAGS_PATTERN = /^[^=&\s]+=[^&\s]*(?:&[^=&\s]+=[^&\s]*)*$/
const MIN_IMAGE_WIDTH = 600
const VERTICAL_RATIO = 9 / 16
const INSTAGRAM_FEED_CARDS = 5

export function adRows(args: CreateAdsArgs): AdRow[] {
  const forced = hasAiGeneratedChange(args.catalogue, args.enabledChanges)
  const names = new Map<string, number>()
  for (const ad of args.ads) {
    const key = ad.name.trim().toLocaleLowerCase()
    names.set(key, (names.get(key) ?? 0) + 1)
  }
  return args.ads.map((ad) => {
    const objectives = ad.adSetIds.map((id) => args.adSets.get(id)?.objective ?? null)
    const buttons = allowedButtons(args.buttons, objectives)
    const callToAction = ad.overrides.callToAction ?? args.shared.callToAction ?? DEFAULT_BUTTON
    const link = ad.overrides.link ?? args.shared.link
    const urlTags = ad.overrides.urlTags ?? args.shared.urlTags
    const checks = [
      ...textChecks(ad),
      ...linkChecks(ad, link, urlTags),
      ...buttonChecks(ad, callToAction, buttons),
      ...mediaChecks(ad),
    ]
    if ((names.get(ad.name.trim().toLocaleLowerCase()) ?? 0) > 1) {
      checks.unshift({ level: "error", message: "Another ad has the same name.", field: "name" })
    }
    return {
      ad,
      link,
      callToAction,
      urlTags,
      status: forced ? "paused" : (ad.overrides.status ?? args.shared.status),
      statusForced: forced,
      allowedButtons: buttons,
      checks,
      check: hasError(checks) ? "error" : checks.length > 0 ? "warning" : "ready",
    }
  })
}

function textChecks(ad: AdDraft): AdCheck[] {
  const checks: AdCheck[] = []
  const error = (field: CheckField, message: string) => {
    checks.push({ level: "error", message, field })
  }
  if (!ad.name.trim()) error("name", "Give the ad a name.")
  if (ad.name.length > NAME_LIMIT) {
    error("name", `Names can be at most ${String(NAME_LIMIT)} characters.`)
  }
  if (!ad.primaryText.trim()) error("primary_text", "Write the primary text.")
  if (ad.primaryText.length > PRIMARY_TEXT_LIMIT) {
    error("primary_text", `Primary text can be at most ${String(PRIMARY_TEXT_LIMIT)} characters.`)
  }
  if ((ad.primaryText.match(HASHTAG_PATTERN) ?? []).length > HASHTAG_LIMIT) {
    error("primary_text", `Instagram allows at most ${String(HASHTAG_LIMIT)} hashtags.`)
  }
  if (ad.format !== "carousel" && !ad.headline?.trim()) error("headline", "Write a headline.")
  for (const [field, value] of [
    ["headline", ad.headline],
    ["description", ad.description],
  ] as const) {
    if (value && value.length > TEXT_LIMIT) {
      error(field, `This can be at most ${String(TEXT_LIMIT)} characters.`)
    }
  }
  for (const [position, card] of ad.cards.entries()) {
    const name = `Card ${String(position + 1)}`
    if (!card.headline.trim()) error("cards", `${name} needs a headline.`)
    if (card.headline.length > TEXT_LIMIT || (card.description?.length ?? 0) > TEXT_LIMIT) {
      error("cards", `${name}'s text can be at most ${String(TEXT_LIMIT)} characters.`)
    }
  }
  pushLength(checks, "primary_text", ad.primaryText, RECOMMENDED_LENGTHS.primaryText)
  if (ad.format !== "carousel") {
    pushLength(checks, "headline", ad.headline, RECOMMENDED_LENGTHS.headline)
    pushLength(checks, "description", ad.description, RECOMMENDED_LENGTHS.description)
  }
  return checks
}

// Card text has a counter on each card, so only the ad's own text gets a cut-off warning.
function pushLength(checks: AdCheck[], field: CheckField, value: string | null, limit: number) {
  if (value && value.length > limit) {
    checks.push({
      level: "warning",
      message: `Over Meta's recommended ${String(limit)} characters. That's allowed, but some placements cut it off.`,
      field,
    })
  }
}

function linkChecks(ad: AdDraft, link: string | null, urlTags: string | null): AdCheck[] {
  const checks: AdCheck[] = []
  if (!link) checks.push({ level: "error", message: "Add a website link.", field: "link" })
  else if (!isHttpsLink(link)) {
    checks.push({ level: "error", message: "Use a full https:// link.", field: "link" })
  }
  for (const [position, card] of ad.cards.entries()) {
    if (card.link && !isHttpsLink(card.link)) {
      checks.push({
        level: "error",
        message: `Card ${String(position + 1)} needs a full https:// link.`,
        field: "cards",
      })
    }
  }
  if (urlTags && !URL_TAGS_PATTERN.test(urlTags)) {
    checks.push({
      level: "error",
      message: "Write URL tags as key=value pairs joined by &.",
      field: "url_tags",
    })
  }
  return checks
}

function buttonChecks(ad: AdDraft, callToAction: string, buttons: readonly string[]): AdCheck[] {
  const message = (button: string) =>
    `${fieldOptionLabel(button)} isn't available for this ad's goal.`
  if (!buttons.includes(callToAction)) {
    return [{ level: "error", message: message(callToAction), field: "call_to_action" }]
  }
  const card = ad.cards.find((item) => item.callToAction && !buttons.includes(item.callToAction))
  return card?.callToAction
    ? [{ level: "error", message: message(card.callToAction), field: "cards" }]
    : []
}

function mediaChecks(ad: AdDraft): AdCheck[] {
  const checks: AdCheck[] = []
  const images = [ad.media, ...ad.cards.map((card) => card.media)].filter(
    (item): item is PreviewMedia => item?.mediaType === "image"
  )
  if (images.some((item) => item.width !== null && item.width < MIN_IMAGE_WIDTH)) {
    checks.push({
      level: "warning",
      message: `An image is under ${String(MIN_IMAGE_WIDTH)} pixels wide, so it can look blurry.`,
      field: "media",
    })
  }
  const vertical = ad.verticalMedia
  if (
    vertical?.width &&
    vertical.height &&
    Math.abs(vertical.width / vertical.height - VERTICAL_RATIO) > 0.03
  ) {
    checks.push({
      level: "warning",
      message: "The vertical version isn't 9:16, so Stories and Reels crop it.",
      field: "media",
    })
  }
  if (ad.format === "carousel" && ad.cards.length < MIN_CARDS) {
    checks.push({
      level: "error",
      message: `A carousel needs at least ${String(MIN_CARDS)} cards.`,
      field: "cards",
    })
  }
  if (ad.cards.length > MAX_CARDS) {
    checks.push({
      level: "error",
      message: `A carousel can have at most ${String(MAX_CARDS)} cards.`,
      field: "cards",
    })
  }
  const repeated = repeatedCards(ad.cards)
  if (repeated) {
    checks.push({
      level: "error",
      message: `Cards ${String(repeated[0] + 1)} and ${String(repeated[1] + 1)} use the same media. Change one.`,
      field: "cards",
    })
  }
  const all = [ad.media, ad.verticalMedia, ...ad.cards.map((card) => card.media)]
  if (all.some((item) => item && !item.ready)) {
    checks.push({
      level: "error",
      message: "Meta is still processing a video. Choose another, or wait until it's ready.",
      field: ad.format === "carousel" ? "cards" : "media",
    })
  }
  if (ad.cards.length > INSTAGRAM_FEED_CARDS) {
    checks.push({
      level: "warning",
      message: `Instagram Feed shows only the first ${String(INSTAGRAM_FEED_CARDS)} cards.`,
      field: "cards",
    })
  }
  return checks
}

// Meta needs different media on each card; returns the first two positions that repeat.
function repeatedCards(cards: readonly Card[]): [number, number] | null {
  const seen = new Map<string, number>()
  for (const [position, card] of cards.entries()) {
    const first = seen.get(card.media.key)
    if (first !== undefined) return [first, position]
    seen.set(card.media.key, position)
  }
  return null
}

function isHttpsLink(value: string): boolean {
  try {
    if (/\s/.test(value)) return false
    const url = new URL(value)
    return url.protocol === "https:" && Boolean(url.hostname) && !url.username && !url.password
  } catch {
    return false
  }
}

/** Blocks approval while any ad has an error the server would reject. */
export function createAdsProblem(args: CreateAdsArgs | null): string | null {
  if (!args) return null
  const rows = adRows(args)
  const failing = rows.filter((row) => row.check === "error").length
  return failing
    ? `Fix ${String(failing)} ${pluralize(failing, "ad")} with errors before approving, or decline this request.`
    : null
}

// What creating the ads means for each ad set they go into.
export type Delivery = "paused" | "ad_set_off" | "campaign_off" | "runs"

export function adSetDelivery(args: CreateAdsArgs, rows: readonly AdRow[]): Map<string, Delivery> {
  const delivery = new Map<string, Delivery>()
  for (const adSetId of new Set(rows.flatMap((row) => row.ad.adSetIds))) {
    const adSet = args.adSets.get(adSetId)
    const active = rows.some((row) => row.status === "active" && row.ad.adSetIds.includes(adSetId))
    delivery.set(
      adSetId,
      !active
        ? "paused"
        : adSet?.status !== "ACTIVE"
          ? "ad_set_off"
          : adSet.effectiveStatus === "CAMPAIGN_PAUSED"
            ? "campaign_off"
            : "runs"
    )
  }
  return delivery
}

/** Says, per ad set, what creating these ads means for delivery and spend. */
export function statusLines(args: CreateAdsArgs, rows: readonly AdRow[]): string[] {
  const lines = new Map<string, string[]>()
  for (const [adSetId, delivery] of adSetDelivery(args, rows)) {
    const adSet = args.adSets.get(adSetId)
    const one = rows.filter((row) => row.ad.adSetIds.includes(adSetId)).length === 1
    const [them, they] = one ? ["it", "It"] : ["them", "They"]
    const line =
      delivery === "paused"
        ? `Created paused. Nothing runs or spends until you turn ${them} on.`
        : delivery === "ad_set_off"
          ? `${they} won't run until the ad set is turned on.`
          : delivery === "campaign_off"
            ? `${they} won't run until the campaign is turned on.`
            : `${they} ${one ? "starts" : "start"} running once Meta approves ${them}${adSet ? budgetPhrase(adSet, args.currency) : ""}.`
    lines.set(line, [...(lines.get(line) ?? []), adSetName(args, adSetId)])
  }
  // With one ad set, or one outcome for all of them, the ad set names add nothing.
  if (lines.size === 1) return [...lines.keys()]
  return [...lines].map(([line, names]) => `${names.join(", ")}: ${line}`)
}

function budgetPhrase(adSet: AdSetInfo, currency: string | null): string {
  const budget = adSet.budget
  if (!budget?.amount || !currency) return ""
  const amount = formatCurrencyAmount(budget.amount, currency)
  const period = budget.kind === "campaign" ? budget.period : budget.kind
  const holder = budget.kind === "campaign" ? "its campaign's" : "this ad set's"
  return `, within ${holder} ${amount} ${period === "lifetime" ? "in total" : "a day"}`
}

export function checksFor(row: AdRow, field: CheckField): AdCheck[] {
  return row.checks.filter((check) => check.field === field)
}

export function hasError(checks: readonly AdCheck[]): boolean {
  return checks.some((check) => check.level === "error")
}
