// apps/web/src/integrations/google_ads/lib/update-campaigns-result.ts

import {
  CAMPAIGN_SETTINGS,
  type CampaignSetting,
  type SettingValue,
  type UrlParameter,
} from "@/integrations/google_ads/lib/update-campaigns"
import { isNonEmptyString, isRecord } from "@/lib/guards"

export type CampaignOutcome = "updated" | "already_set" | "failed" | "unverified"

export type CampaignOutcomeRow = {
  after: SettingValue
  before: SettingValue
  campaignName: string
  errorCode: string | null
  message: string | null
  outcome: CampaignOutcome
  readBack: boolean
  setting: CampaignSetting
}

export type UpdateCampaignsResult = { accountId: string; rows: CampaignOutcomeRow[] }

const OUTCOMES: readonly string[] = ["updated", "already_set", "failed", "unverified"]

function value(raw: unknown): SettingValue | undefined {
  if (raw === null || typeof raw === "string" || typeof raw === "boolean") return raw
  if (!Array.isArray(raw)) return undefined
  const items: UrlParameter[] = []
  for (const item of raw) {
    if (!isRecord(item) || typeof item["key"] !== "string" || typeof item["value"] !== "string")
      return undefined
    items.push({ key: item["key"], value: item["value"] })
  }
  return items
}

function parseCampaign(raw: unknown): CampaignOutcomeRow[] | null {
  if (!isRecord(raw) || !isNonEmptyString(raw["name"]) || !Array.isArray(raw["settings"]))
    return null
  const text = (key: string) => (typeof raw[key] === "string" ? raw[key] : null)
  const rows: CampaignOutcomeRow[] = []
  for (const item of raw["settings"]) {
    if (!isRecord(item)) return null
    const { outcome, setting } = item
    const before = value(item["before"])
    const after = value(item["after"])
    if (
      typeof setting !== "string" ||
      !(CAMPAIGN_SETTINGS as readonly string[]).includes(setting) ||
      typeof outcome !== "string" ||
      !OUTCOMES.includes(outcome) ||
      before === undefined ||
      after === undefined
    )
      return null
    rows.push({
      after,
      before,
      campaignName: raw["name"],
      errorCode: text("error_code"),
      message: text("message"),
      outcome: outcome as CampaignOutcome,
      readBack: raw["read_back"] === true,
      setting: setting as CampaignSetting,
    })
  }
  return rows
}

export function parseUpdateCampaignsResult(raw: unknown): UpdateCampaignsResult | null {
  if (!isRecord(raw) || !isNonEmptyString(raw["account_id"]) || !Array.isArray(raw["campaigns"]))
    return null
  const campaigns = raw["campaigns"].map(parseCampaign)
  if (campaigns.some((rows) => rows === null)) return null
  return { accountId: raw["account_id"], rows: campaigns.flatMap((rows) => rows ?? []) }
}

export function campaignsOutcomeSummary(result: UpdateCampaignsResult): string {
  const count = (outcome: CampaignOutcome) =>
    result.rows.filter((row) => row.outcome === outcome).length
  return [
    [count("updated"), "changed"],
    [count("already_set"), "already set"],
    [count("failed"), "failed"],
    [count("unverified"), "unconfirmed"],
  ]
    .filter(([total]) => total !== 0)
    .map(([total, label]) => `${String(total)} ${String(label)}`)
    .join(" · ")
}
