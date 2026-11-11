// apps/web/src/integrations/google_ads/lib/new-assets.ts

import { collapseSpaces } from "@/integrations/ads/lib/keyword-notation"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import { characterCount } from "@/integrations/google_ads/lib/create-ads"
import { isGoogleAdsUrl } from "@/integrations/google_ads/lib/field-values"
import { isRecord } from "@/lib/guards"

export type AssetType = "SITELINK" | "CALLOUT" | "STRUCTURED_SNIPPET" | "CALL" | "PRICE" | "IMAGE"
// The types the operator can write, by the tool's `type` value.
export type ContentType = Exclude<AssetType, "IMAGE">

export const ASSET_TYPES: readonly AssetType[] = [
  "SITELINK",
  "CALLOUT",
  "STRUCTURED_SNIPPET",
  "CALL",
  "PRICE",
  "IMAGE",
]

export const ASSET_TYPE_LABELS: Record<AssetType, string> = {
  CALL: "Call",
  CALLOUT: "Callout",
  IMAGE: "Image",
  PRICE: "Price",
  SITELINK: "Sitelink",
  STRUCTURED_SNIPPET: "Structured Snippet",
}

const CONTENT_TYPES: Record<string, ContentType> = {
  call: "CALL",
  callout: "CALLOUT",
  price: "PRICE",
  sitelink: "SITELINK",
  structured_snippet: "STRUCTURED_SNIPPET",
}

/** The tool's `type` value for each type the operator can write. */
export const CONTENT_TYPE_VALUES: Record<ContentType, string> = {
  CALL: "call",
  CALLOUT: "callout",
  PRICE: "price",
  SITELINK: "sitelink",
  STRUCTURED_SNIPPET: "structured_snippet",
}

type Option = { value: string; label: string }

// Google's English headers, as the server takes them.
const SNIPPET_HEADERS = [
  "Amenities",
  "Brands",
  "Courses",
  "Degree programs",
  "Destinations",
  "Featured hotels",
  "Insurance coverage",
  "Models",
  "Neighborhoods",
  "Service catalog",
  "Shows",
  "Styles",
  "Types",
]
const PRICE_TYPES: readonly Option[] = [
  { label: "Brands", value: "BRANDS" },
  { label: "Events", value: "EVENTS" },
  { label: "Locations", value: "LOCATIONS" },
  { label: "Neighbourhoods", value: "NEIGHBORHOODS" },
  { label: "Product Categories", value: "PRODUCT_CATEGORIES" },
  { label: "Product Tiers", value: "PRODUCT_TIERS" },
  { label: "Services", value: "SERVICES" },
  { label: "Service Categories", value: "SERVICE_CATEGORIES" },
  { label: "Service Tiers", value: "SERVICE_TIERS" },
]
const PRICE_QUALIFIERS: readonly Option[] = [
  { label: "No Qualifier", value: "" },
  { label: "From", value: "FROM" },
  { label: "Up To", value: "UP_TO" },
  { label: "Average", value: "AVERAGE" },
]
export const PRICE_UNITS: readonly Option[] = [
  { label: "No Unit", value: "" },
  { label: "Per Hour", value: "PER_HOUR" },
  { label: "Per Day", value: "PER_DAY" },
  { label: "Per Week", value: "PER_WEEK" },
  { label: "Per Month", value: "PER_MONTH" },
  { label: "Per Year", value: "PER_YEAR" },
  { label: "Per Night", value: "PER_NIGHT" },
]

// Each editable field's argument name and label, with Google's limit on its text.
type TextField = { key: string; label: string; limit: number; kind: "text"; optional?: boolean }
type ChoiceField = {
  key: string
  label: string
  kind: "choice"
  options: readonly Option[]
  optional?: boolean
}
// A list entered as comma-separated text, with each item's limit and the list's size.
type ListField = {
  key: string
  label: string
  kind: "list"
  limit: number
  min: number
  max: number
}
export type AssetField = TextField | ChoiceField | ListField

const SITELINK_FIELDS: readonly AssetField[] = [
  { key: "link_text", kind: "text", label: "Link Text", limit: 25 },
  { key: "description1", kind: "text", label: "Description 1", limit: 35, optional: true },
  { key: "description2", kind: "text", label: "Description 2", limit: 35, optional: true },
  { key: "final_url", kind: "text", label: "Final URL", limit: 2048 },
]
const CALLOUT_FIELDS: readonly AssetField[] = [
  { key: "text", kind: "text", label: "Text", limit: 25 },
]
const SNIPPET_FIELDS: readonly AssetField[] = [
  {
    key: "header",
    kind: "choice",
    label: "Header",
    options: SNIPPET_HEADERS.map((header) => ({ label: header, value: header })),
  },
  { key: "values", kind: "list", label: "Values", limit: 25, max: 10, min: 3 },
]
const CALL_FIELDS: readonly AssetField[] = [
  { key: "country_code", kind: "text", label: "Country", limit: 2 },
  { key: "phone_number", kind: "text", label: "Phone Number", limit: 32 },
]
// A price's offerings are edited in their own table.
const PRICE_FIELDS: readonly AssetField[] = [
  { key: "price_type", kind: "choice", label: "Type", options: PRICE_TYPES },
  {
    key: "price_qualifier",
    kind: "choice",
    label: "Qualifier",
    optional: true,
    options: PRICE_QUALIFIERS,
  },
  { key: "currency_code", kind: "text", label: "Currency", limit: 3 },
]

export const ASSET_FIELDS: Record<AssetType, readonly AssetField[]> = {
  CALL: CALL_FIELDS,
  CALLOUT: CALLOUT_FIELDS,
  IMAGE: [],
  PRICE: PRICE_FIELDS,
  SITELINK: SITELINK_FIELDS,
  STRUCTURED_SNIPPET: SNIPPET_FIELDS,
}

// A price takes 3 to 8 offerings, each with a header and description of up to 25 characters.
const MIN_OFFERINGS = 3
export const MAX_OFFERINGS = 8
export const OFFERING_TEXT_LIMIT = 25

// Google's limit for one campaign or ad group, as the tools take it.
export const MAX_ASSETS_PER_TARGET = 20
// Google shows no sitelinks to a campaign with one, and shows them best with four.
const SITELINKS_ADVISED = 4

/** A new sitelink or callout in the tool's own shape, `{type: "sitelink", link_text, …}`. */
export type DraftAsset = Record<string, unknown>

/** Google's rejection of a new asset, named by its content. */
export type AssetProblem = { key: string; message: string }

export function draftAssetType(asset: DraftAsset): ContentType {
  return CONTENT_TYPES[String(asset["type"])] ?? "CALLOUT"
}

/** Reads a new sitelink or callout, the types the create cards take. */
export function parseNewAsset(value: unknown): DraftAsset | null {
  return isRecord(value) && (value["type"] === "sitelink" || value["type"] === "callout")
    ? value
    : null
}

/** Reads a new asset of any type Update Ad Assets takes. */
export function parseContentAsset(value: unknown): DraftAsset | null {
  return isRecord(value) && String(value["type"]) in CONTENT_TYPES ? value : null
}

export function blankAsset(type: AssetType): DraftAsset {
  return type === "SITELINK"
    ? { type: "sitelink", link_text: "", description1: "", description2: "", final_url: "" }
    : { type: "callout", text: "" }
}

function text(value: unknown): string {
  return typeof value === "string" ? collapseSpaces(value) : ""
}

function url(value: unknown): string {
  return typeof value === "string" ? value.trim() : ""
}

export function textList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(text) : []
}

export function offeringList(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter(isRecord) : []
}

/** A snippet header as the server takes it, whatever its case. */
function snippetHeader(value: unknown): string {
  const typed = text(value)
  return SNIPPET_HEADERS.find((header) => header.toLowerCase() === typed.toLowerCase()) ?? typed
}

/** A phone number as the server sends it: its digits, after a leading + if there is one. */
function phoneDigits(value: unknown): string {
  const typed = text(value).replace(/\s/g, "")
  const digits = typed.replace(/\D/g, "")
  return typed.startsWith("+") ? `+${digits}` : digits
}

function upper(value: unknown): string {
  return text(value).toUpperCase()
}

// Each type's content as the server keys it, in its order.
function keyParts(asset: DraftAsset): string[] {
  switch (draftAssetType(asset)) {
    case "SITELINK":
      return [
        text(asset["link_text"]),
        text(asset["description1"]),
        text(asset["description2"]),
        url(asset["final_url"]),
        ...dates(asset),
      ]
    case "CALLOUT":
      return [text(asset["text"]), ...dates(asset)]
    case "STRUCTURED_SNIPPET":
      return [snippetHeader(asset["header"]), ...textList(asset["values"])]
    case "CALL":
      return [upper(asset["country_code"]), phoneDigits(asset["phone_number"])]
    case "PRICE":
      return [
        text(asset["price_type"]),
        text(asset["price_qualifier"]),
        text(asset["language_code"]) || "en",
        upper(asset["currency_code"]),
        ...offeringList(asset["offerings"]).flatMap((offering) => [
          text(offering["header"]),
          text(offering["description"]),
          text(offering["price"]),
          text(offering["unit"]),
          url(offering["final_url"]),
        ]),
      ]
  }
}

// The server names a date by its day, whatever time came with it.
function dates(asset: DraftAsset): string[] {
  return [text(asset["start_date"]).slice(0, 10), text(asset["end_date"]).slice(0, 10)]
}

/** The server's name for a new asset: its content as plain text, in a fixed order. */
export function newAssetKey(asset: DraftAsset): string {
  return ["new", String(asset["type"]), ...keyParts(asset)].join("|")
}

/** What the card calls an asset: a sitelink's text, a snippet's header and values, a call's number. */
export function draftAssetLabel(asset: DraftAsset): string {
  switch (draftAssetType(asset)) {
    case "SITELINK":
      return text(asset["link_text"])
    case "CALLOUT":
      return text(asset["text"])
    case "STRUCTURED_SNIPPET":
      return `${snippetHeader(asset["header"])}: ${textList(asset["values"]).join(", ")}`
    case "CALL":
      return phoneDigits(asset["phone_number"])
    case "PRICE":
      return offeringList(asset["offerings"])
        .map((offering) => text(offering["header"]))
        .join(", ")
  }
}

function textFieldProblem(field: TextField, value: string): string | null {
  const length = characterCount(value)
  if (length === 0) return field.optional ? null : `${field.label} is required.`
  if (length > field.limit)
    return `${field.label} is ${String(length)} of ${String(field.limit)} characters.`
  if (field.key === "final_url" && !isGoogleAdsUrl(value))
    return "Enter a complete web address, starting with https://."
  if (field.key === "country_code" && !/^[A-Za-z]{2}$/.test(value))
    return "Enter the two-letter country code, such as GB."
  if (field.key === "currency_code" && !/^[A-Za-z]{3}$/.test(value))
    return "Enter the three-letter currency code, such as GBP."
  if (field.key === "phone_number") {
    const digits = value.replace(/\D/g, "").length
    if (digits < 6 || digits > 16 || /[^\d\s+\-().]/.test(value))
      return "Enter a phone number of 6 to 16 digits."
  }
  return null
}

function listProblem(field: ListField, values: string[]): string | null {
  if (values.length < field.min || values.length > field.max)
    return `${field.label}: add ${String(field.min)} to ${String(field.max)}, separated by commas.`
  const long = values.find((value) => characterCount(value) > field.limit || !value)
  if (long !== undefined)
    return `${field.label}: each one can have 1 to ${String(field.limit)} characters.`
  if (new Set(values.map((value) => value.toLowerCase())).size !== values.length)
    return `${field.label}: list each one once.`
  return null
}

function fieldValueProblem(field: AssetField, value: unknown): string | null {
  if (field.kind === "list") return listProblem(field, textList(value))
  if (field.kind === "choice") {
    const chosen = field.key === "header" ? snippetHeader(value) : text(value)
    if (!chosen) return field.optional ? null : `Choose a ${field.label.toLowerCase()}.`
    return field.options.some((option) => option.value === chosen)
      ? null
      : `Choose a ${field.label.toLowerCase()} from the list.`
  }
  return textFieldProblem(field, text(value))
}

/** Why a price's offerings can't be sent, or null. */
function offeringsProblem(value: unknown): string | null {
  const offerings = offeringList(value)
  if (offerings.length < MIN_OFFERINGS || offerings.length > MAX_OFFERINGS)
    return `A price needs ${String(MIN_OFFERINGS)} to ${String(MAX_OFFERINGS)} items.`
  for (const [index, offering] of offerings.entries()) {
    const name = `Item ${String(index + 1)}`
    for (const key of ["header", "description"] as const) {
      const length = characterCount(text(offering[key]))
      if (length === 0 || length > OFFERING_TEXT_LIMIT)
        return `${name}: the ${key} needs 1 to ${String(OFFERING_TEXT_LIMIT)} characters.`
    }
    const price = text(offering["price"])
    if (!/^\d+(?:\.\d{1,6})?$/.test(price) || Number(price) <= 0)
      return `${name}: enter the price as a number greater than zero, such as 49.99.`
    if (!isGoogleAdsUrl(url(offering["final_url"])))
      return `${name}: enter a complete web address, starting with https://.`
  }
  const headers = offerings.map((offering) => text(offering["header"]).toLowerCase())
  return new Set(headers).size === headers.length ? null : "Give each item a different header."
}

/** Why a new or edited asset's fields can't be sent, or null. */
export function fieldProblem(asset: DraftAsset): string | null {
  const type = draftAssetType(asset)
  for (const field of ASSET_FIELDS[type]) {
    const problem = fieldValueProblem(field, asset[field.key])
    if (problem) return problem
  }
  if (type === "SITELINK" && !text(asset["description1"]) !== !text(asset["description2"]))
    return "Add both description lines, or neither."
  return type === "PRICE" ? offeringsProblem(asset["offerings"]) : null
}

/** When an asset can show, such as "From 2026-12-01 to 2026-12-24"; null when it has no dates. */
export function assetDatesText(start: unknown, end: unknown): string | null {
  const from = text(start).slice(0, 10)
  const to = text(end).slice(0, 10)
  if (from && to) return `From ${from} to ${to}`
  if (from) return `From ${from}`
  return to ? `Until ${to}` : null
}

export function blankIsNull(value: unknown): unknown {
  return typeof value === "string" && !value.trim() ? null : value
}

/** The `assets` value for the drafts; blank optional fields are null. */
export function serializeNewAssets(assets: readonly DraftAsset[]): Record<string, unknown>[] {
  return assets.map((asset) => {
    const dates = {
      start_date: blankIsNull(asset["start_date"] ?? null),
      end_date: blankIsNull(asset["end_date"] ?? null),
    }
    return asset["type"] === "sitelink"
      ? {
          type: "sitelink",
          link_text: asset["link_text"] ?? "",
          description1: blankIsNull(asset["description1"] ?? null),
          description2: blankIsNull(asset["description2"] ?? null),
          final_url: asset["final_url"] ?? "",
          ...dates,
        }
      : { type: "callout", text: asset["text"] ?? "", ...dates }
  })
}

/** Names each asset as the card does: "Sitelink 2", counted within its type. */
export function assetLabels(assets: readonly DraftAsset[]): string[] {
  const seen = new Map<AssetType, number>()
  return assets.map((asset) => {
    const type = draftAssetType(asset)
    const position = (seen.get(type) ?? 0) + 1
    seen.set(type, position)
    return `${ASSET_TYPE_LABELS[type]} ${String(position)}`
  })
}

/** The size and repeat rules for one campaign or ad group; each list holds its assets' keys. */
export function assetListProblems(
  subject: string,
  lists: readonly (readonly string[])[]
): string[] {
  const keys = lists.flat()
  return [
    ...(lists.some((list) => list.length > MAX_ASSETS_PER_TARGET)
      ? [`${subject}: at most ${String(MAX_ASSETS_PER_TARGET)} at a time.`]
      : []),
    ...(new Set(keys).size !== keys.length ? [`${subject}: list each one once.`] : []),
  ]
}

/** What the card can find without asking Google: field limits, repeats, and the count. */
export function newAssetProblems(assets: readonly DraftAsset[]): string[] {
  const labels = assetLabels(assets)
  return [
    ...assets.flatMap((asset, index) => {
      const problem = fieldProblem(asset)
      return problem ? [`${String(labels[index])}: ${problem}`] : []
    }),
    ...assetListProblems("Sitelinks and callouts", [assets.map(newAssetKey)]),
  ]
}

/** Google's rejections from the last check, once each, while the asset it rejected is still here. */
export function googleAssetProblems(
  assets: readonly DraftAsset[],
  problems: readonly AssetProblem[]
): string[] {
  const labels = new Map(
    assetLabels(assets).map((label, index) => [newAssetKey(assets[index] ?? {}), label])
  )
  const lines = problems.flatMap((problem) => {
    const label = labels.get(problem.key)
    return label ? [`${label}: ${problem.message}`] : []
  })
  return [...new Set(lines)]
}

/** True for a problem `newAssetProblems` or `googleAssetProblems` gave, to colour its row. */
export function isAssetProblem(problem: string): boolean {
  return /^(Sitelink \d|Callout \d|Sitelinks and callouts:)/.test(problem)
}

export function assetSummary(assets: readonly DraftAsset[]): string {
  const sitelinks = assets.filter((asset) => draftAssetType(asset) === "SITELINK").length
  const callouts = assets.length - sitelinks
  if (assets.length === 0) return "No sitelinks or callouts"
  return [
    sitelinks ? approvalCountLine(sitelinks, "sitelink") : null,
    callouts ? approvalCountLine(callouts, "callout") : null,
  ]
    .filter(Boolean)
    .join(", ")
}

/** Advice that doesn't block approval, for a campaign or ad group left with too few sitelinks. */
export function sitelinkAdvice(sitelinks: number): string | null {
  return sitelinks < SITELINKS_ADVISED
    ? `Google shows sitelinks only with 2 or more, and best with ${String(SITELINKS_ADVISED)} or more.`
    : null
}
