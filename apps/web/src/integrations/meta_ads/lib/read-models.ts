// apps/web/src/integrations/meta_ads/lib/read-models.ts

import {
  isDateString,
  isDateTimeString,
  isNonEmptyString,
  isNonNegativeInteger,
  isNullableFiniteNumber,
  isOneOf,
  isRecord,
  isStringArray,
} from "@/lib/guards"

export type MetaAdsAccount = {
  name: string | null
  status: string
  disable_reason: string | null
  currency: string
  timezone_name: string | null
  amount_spent: string | null
  spend_cap: string | null
  spend_cap_remaining: string | null
  balance: string | null
  min_daily_budget: string | null
}

type MetaAdsBudget = {
  kind: "daily" | "lifetime" | "campaign"
  amount: string | null
  remaining: string | null
}
type MetaAdsObject = {
  id: string
  name: string | null
  status: string | null
  effective_status: string | null
  objective: string | null
  optimization_goal: string | null
  bid_strategy: string | null
  start_time: string | null
  end_time: string | null
  campaign_id: string | null
  adset_id: string | null
  budget: MetaAdsBudget | null
  bid_amount: string | null
  // Ads only: why Meta's review rejected the ad, and what stops it delivering.
  review_reasons?: string[] | null
  issues?: string[] | null
}
type MetaAdsObjects = {
  object_type: "campaign" | "adset" | "ad"
  objects: MetaAdsObject[]
  object_count: number
  truncated: boolean
  currency: string
}
export type MetaAdsConversion = {
  kind: "custom_conversion" | "custom_event"
  action_type: string
  id: string | null
  name: string | null
  description: string | null
  is_archived: boolean | null
  is_unavailable: boolean | null
  recent_conversions: number | null
}
type MetaAdsConversions = {
  conversions: MetaAdsConversion[]
  conversion_count: number
  truncated: boolean
  notes: string[]
  recent_since: string | null
  recent_until: string | null
}

type MetaAdsActivity = {
  event_time: string
  event_type: string | null
  translated_event_type: string | null
  object_type: string | null
  object_id: string | null
  object_name: string | null
  actor_name: string | null
  old_value: string | null
  new_value: string | null
}
type MetaAdsActivities = {
  events: MetaAdsActivity[]
  event_count: number
  truncated: boolean
  window_note: string | null
  timezone_name: string
}

export const UNRESOLVED_CONVERSION_NAME = "Custom conversion (name unavailable)"
export const CUSTOM_CONVERSION_PREFIX = "offsite_conversion.custom."
export const CUSTOM_EVENT_PREFIX = "offsite_conversion.fb_pixel_custom."

const OBJECT_TYPES: ReadonlySet<MetaAdsObjects["object_type"]> = new Set([
  "campaign",
  "adset",
  "ad",
])
const BUDGET_KINDS: ReadonlySet<MetaAdsBudget["kind"]> = new Set(["daily", "lifetime", "campaign"])

function isNullableMetaText(value: unknown): value is string | null {
  return value === null || (typeof value === "string" && value.length <= 512)
}
function isId(value: unknown): value is string {
  return typeof value === "string" && /^[0-9]{1,128}$/.test(value)
}
function isNullableId(value: unknown): value is string | null {
  return value === null || isId(value)
}
function isNullableDate(value: unknown): value is string | null {
  return value === null || isDateString(value)
}

function isCurrency(value: unknown): value is string {
  return typeof value === "string" && /^[A-Z]{3}$/.test(value)
}
function isMoney(value: unknown): value is string | null {
  return (
    value === null ||
    (typeof value === "string" && value.length <= 520 && /^-?\d+(?:\.\d+)?$/.test(value))
  )
}
function isNullableChangeValue(value: unknown): value is string | null {
  return value === null || (typeof value === "string" && value.length <= 256)
}
function isNullableBoolean(value: unknown): value is boolean | null {
  return value === null || typeof value === "boolean"
}
function isNullableDateTime(value: unknown): value is string | null {
  return value === null || isDateTimeString(value)
}

export function parseMetaAdsAccount(value: unknown): MetaAdsAccount | null {
  if (
    !isRecord(value) ||
    !isNullableMetaText(value["name"]) ||
    !isNonEmptyString(value["status"]) ||
    value["status"].length > 512 ||
    !isNullableMetaText(value["disable_reason"]) ||
    !isCurrency(value["currency"]) ||
    !isNullableMetaText(value["timezone_name"]) ||
    !isMoney(value["amount_spent"]) ||
    !isMoney(value["spend_cap"]) ||
    !isMoney(value["spend_cap_remaining"]) ||
    !isMoney(value["balance"]) ||
    !isMoney(value["min_daily_budget"])
  )
    return null
  return {
    name: value["name"],
    status: value["status"],
    disable_reason: value["disable_reason"],
    currency: value["currency"],
    timezone_name: value["timezone_name"],
    amount_spent: value["amount_spent"],
    spend_cap: value["spend_cap"],
    spend_cap_remaining: value["spend_cap_remaining"],
    balance: value["balance"],
    min_daily_budget: value["min_daily_budget"],
  }
}

function isBudget(value: unknown): value is MetaAdsBudget | null {
  return (
    value === null ||
    (isRecord(value) &&
      isOneOf(BUDGET_KINDS, value["kind"]) &&
      isMoney(value["amount"]) &&
      isMoney(value["remaining"]))
  )
}
function isObject(value: unknown): value is MetaAdsObject {
  return (
    isRecord(value) &&
    isId(value["id"]) &&
    isNullableMetaText(value["name"]) &&
    isNullableMetaText(value["status"]) &&
    isNullableMetaText(value["effective_status"]) &&
    isNullableMetaText(value["objective"]) &&
    isNullableMetaText(value["optimization_goal"]) &&
    isNullableMetaText(value["bid_strategy"]) &&
    isNullableDateTime(value["start_time"]) &&
    isNullableDateTime(value["end_time"]) &&
    isNullableId(value["campaign_id"]) &&
    isNullableId(value["adset_id"]) &&
    isBudget(value["budget"]) &&
    isMoney(value["bid_amount"]) &&
    isOptionalTextList(value["review_reasons"]) &&
    isOptionalTextList(value["issues"])
  )
}
function isOptionalTextList(value: unknown): boolean {
  return value === undefined || value === null || isStringArray(value)
}
export function parseMetaAdsObjects(value: unknown): MetaAdsObjects | null {
  if (
    !isRecord(value) ||
    !isOneOf(OBJECT_TYPES, value["object_type"]) ||
    !Array.isArray(value["objects"]) ||
    !value["objects"].every(isObject) ||
    !isNonNegativeInteger(value["object_count"]) ||
    value["object_count"] < value["objects"].length ||
    typeof value["truncated"] !== "boolean" ||
    !isCurrency(value["currency"])
  )
    return null
  return {
    object_type: value["object_type"],
    objects: value["objects"],
    object_count: value["object_count"],
    truncated: value["truncated"],
    currency: value["currency"],
  }
}
function isConversion(value: unknown): value is MetaAdsConversion {
  return (
    isRecord(value) &&
    hasConversionIdentity(value) &&
    isNullableMetaText(value["name"]) &&
    isNullableMetaText(value["description"]) &&
    isNullableBoolean(value["is_archived"]) &&
    isNullableBoolean(value["is_unavailable"]) &&
    isNullableFiniteNumber(value["recent_conversions"])
  )
}
// Insights reports custom conversions by ID and custom events by name.
function hasConversionIdentity(value: Record<string, unknown>): boolean {
  if (value["kind"] === "custom_conversion")
    return isId(value["id"]) && value["action_type"] === `${CUSTOM_CONVERSION_PREFIX}${value["id"]}`
  return (
    value["kind"] === "custom_event" &&
    value["id"] === null &&
    isNonEmptyString(value["name"]) &&
    value["action_type"] === `${CUSTOM_EVENT_PREFIX}${value["name"]}`
  )
}
export function parseMetaAdsConversions(value: unknown): MetaAdsConversions | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value["conversions"]) ||
    !value["conversions"].every(isConversion) ||
    !isNonNegativeInteger(value["conversion_count"]) ||
    value["conversion_count"] < value["conversions"].length ||
    typeof value["truncated"] !== "boolean" ||
    !isStringArray(value["notes"]) ||
    !isNullableDate(value["recent_since"]) ||
    !isNullableDate(value["recent_until"])
  )
    return null
  return {
    conversions: value["conversions"],
    conversion_count: value["conversion_count"],
    truncated: value["truncated"],
    notes: value["notes"],
    recent_since: value["recent_since"],
    recent_until: value["recent_until"],
  }
}
function isActivity(value: unknown): value is MetaAdsActivity {
  return (
    isRecord(value) &&
    isDateTimeString(value["event_time"]) &&
    isNullableMetaText(value["event_type"]) &&
    isNullableMetaText(value["translated_event_type"]) &&
    isNullableMetaText(value["object_type"]) &&
    isNullableId(value["object_id"]) &&
    isNullableMetaText(value["object_name"]) &&
    isNullableMetaText(value["actor_name"]) &&
    isNullableChangeValue(value["old_value"]) &&
    isNullableChangeValue(value["new_value"])
  )
}
export function parseMetaAdsActivities(value: unknown): MetaAdsActivities | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value["events"]) ||
    !value["events"].every(isActivity) ||
    !isNonNegativeInteger(value["event_count"]) ||
    value["event_count"] < value["events"].length ||
    typeof value["truncated"] !== "boolean" ||
    !isNullableMetaText(value["window_note"]) ||
    !isNonEmptyString(value["timezone_name"]) ||
    value["timezone_name"].length > 512
  )
    return null
  return {
    events: value["events"],
    event_count: value["event_count"],
    truncated: value["truncated"],
    window_note: value["window_note"],
    timezone_name: value["timezone_name"],
  }
}
