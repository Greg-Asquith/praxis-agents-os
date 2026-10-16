// apps/web/src/integrations/meta_ads/lib/launch-result.ts

import { AD_FORMATS, type AdFormat } from "@/integrations/meta_ads/lib/automatic-changes"
import { parseAdOutcomeFields, type AdOutcomeFields } from "@/integrations/meta_ads/lib/ad-outcome"
import {
  parseMediaUploadResult,
  type MediaUploadResult,
} from "@/integrations/meta_ads/lib/media-upload"
import { isNonEmptyString, isOneOf, isRecord, stringValue } from "@/lib/guards"

type LaunchState = "live" | "paused" | "partial" | "stopped"
type TurnOn = "turned_on" | "not_turned_on" | "unverified"
type BuildOutcome = "created" | "failed" | "unverified"

const STATES: ReadonlySet<LaunchState> = new Set(["live", "paused", "partial", "stopped"])
const TURN_ONS: ReadonlySet<TurnOn> = new Set(["turned_on", "not_turned_on", "unverified"])
const OUTCOMES: ReadonlySet<BuildOutcome> = new Set(["created", "failed", "unverified"])

type LaunchObject = {
  name: string
  outcome: BuildOutcome
  recovered: boolean
  id: string | null
  message: string | null
  errorCode: string | null
  // Null unless the launch was asked to go live.
  turnedOn: TurnOn | null
}

type LaunchAdSetResult = LaunchObject & { key: string }
type LaunchAdResult = AdOutcomeFields & {
  outcome: BuildOutcome
  format: AdFormat
  adSetKey: string
  // False when the ad's ad set was never created, so the ad was skipped.
  adSetCreated: boolean
}

export type LaunchResult = {
  accountId: string
  state: LaunchState
  message: string
  goLive: boolean
  campaign: LaunchObject
  adSets: LaunchAdSetResult[]
  ads: LaunchAdResult[]
  uploads: MediaUploadResult["uploads"]
  createdOffForAi: boolean
}

export function parseLaunchResult(value: unknown): LaunchResult | null {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value["account_id"]) ||
    !isOneOf(STATES, value["state"]) ||
    typeof value["message"] !== "string" ||
    !Array.isArray(value["ad_sets"]) ||
    !Array.isArray(value["ads"])
  )
    return null
  const campaign = parseObject(value["campaign"], "campaign_id", value["campaign_turned_on"])
  const uploads = parseMediaUploadResult({
    account_id: value["account_id"],
    uploads: value["uploads"],
  })
  if (!campaign || !uploads) return null
  const adSets: LaunchAdSetResult[] = []
  for (const item of value["ad_sets"]) {
    const adSet = isRecord(item) ? parseObject(item, "adset_id", item["turned_on"]) : null
    if (!isRecord(item) || !adSet || !isNonEmptyString(item["key"])) return null
    adSets.push({ ...adSet, key: item["key"] })
  }
  const ads: LaunchAdResult[] = []
  for (const item of value["ads"]) {
    const ad = parseAd(item)
    if (!ad) return null
    ads.push(ad)
  }
  return {
    accountId: value["account_id"],
    state: value["state"],
    message: value["message"],
    goLive: value["go_live"] === true,
    campaign,
    adSets,
    ads,
    uploads: uploads.uploads,
    createdOffForAi: value["created_off_for_ai"] === true,
  }
}

function parseObject(value: unknown, idKey: string, turnedOn: unknown): LaunchObject | null {
  if (!isRecord(value) || !isNonEmptyString(value["name"]) || !isOneOf(OUTCOMES, value["outcome"]))
    return null
  return {
    name: value["name"],
    outcome: value["outcome"],
    recovered: value["recovered"] === true,
    id: stringValue(value[idKey]),
    message: stringValue(value["message"]),
    errorCode: stringValue(value["error_code"]),
    turnedOn: isOneOf(TURN_ONS, turnedOn) ? turnedOn : null,
  }
}

function parseAd(value: unknown): LaunchAdResult | null {
  if (!isRecord(value) || !isNonEmptyString(value["ad_set_key"])) return null
  // An ad whose ad set was never created has no ad set ID.
  const adSetCreated = isNonEmptyString(value["adset_id"])
  const fields = parseAdOutcomeFields({
    ...value,
    adset_id: adSetCreated ? value["adset_id"] : value["ad_set_key"],
  })
  const { format, outcome } = value
  if (!fields || !isOneOf(AD_FORMATS, format) || !isOneOf(OUTCOMES, outcome)) return null
  return { ...fields, format, outcome, adSetKey: value["ad_set_key"], adSetCreated }
}

/** What to say first, from the state the build ended in. */
export function bannerTone(state: LaunchState): "good" | "neutral" | "warning" {
  if (state === "live") return "good"
  return state === "paused" ? "neutral" : "warning"
}
