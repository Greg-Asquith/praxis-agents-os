// apps/web/src/integrations/meta_ads/lib/create-ads-result.ts

import { AD_FORMATS, type AdFormat } from "@/integrations/meta_ads/lib/automatic-changes"
import { parseAdOutcomeFields, type AdOutcomeFields } from "@/integrations/meta_ads/lib/ad-outcome"
import {
  parseMediaUploadResult,
  type MediaUploadResult,
} from "@/integrations/meta_ads/lib/media-upload"
import { isNonEmptyString, isOneOf, isRecord } from "@/lib/guards"

type CreateOutcome = "created" | "failed" | "unverified"

type CreatedAd = AdOutcomeFields & { format: AdFormat; outcome: CreateOutcome }

export type CreateAdsResult = {
  accountId: string
  ads: CreatedAd[]
  uploads: MediaUploadResult["uploads"]
  createdOffForAi: boolean
}

const OUTCOMES: ReadonlySet<CreateOutcome> = new Set(["created", "failed", "unverified"])

export function parseCreateAdsResult(value: unknown): CreateAdsResult | null {
  if (!isRecord(value) || !isNonEmptyString(value["account_id"]) || !Array.isArray(value["ads"]))
    return null
  const uploads = parseMediaUploadResult({
    account_id: value["account_id"],
    uploads: value["uploads"],
  })
  if (!uploads) return null
  const ads: CreatedAd[] = []
  for (const item of value["ads"]) {
    const ad = parseCreatedAd(item)
    if (!ad) return null
    ads.push(ad)
  }
  return {
    accountId: value["account_id"],
    ads,
    uploads: uploads.uploads,
    createdOffForAi: value["created_off_for_ai"] === true,
  }
}

function parseCreatedAd(value: unknown): CreatedAd | null {
  if (!isRecord(value) || typeof value["recovered"] !== "boolean") return null
  const fields = parseAdOutcomeFields(value)
  const { format, outcome } = value
  if (!fields || !isOneOf(AD_FORMATS, format) || !isOneOf(OUTCOMES, outcome)) return null
  return { ...fields, format, outcome }
}

/** Names what to do next, from what the ads were created as. */
export function nextStep(result: CreateAdsResult): string | null {
  const created = result.ads.filter((ad) => ad.outcome === "created")
  if (created.length === 0) return null
  if (created.some((ad) => ad.unexpectedChanges.length > 0)) {
    return "Meta turned on advanced settings you left off for some ads. Check them in Ads Manager, and ask the agent to pause any that are on."
  }
  return created.every((ad) => ad.requestedStatus === "paused")
    ? "Turn these ads on when Meta approves them. Ask the agent to check their review."
    : "Active ads start running once Meta approves them."
}
