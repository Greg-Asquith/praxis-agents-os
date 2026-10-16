// apps/web/src/integrations/meta_ads/lib/launch-model.ts

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { budgetMoney } from "@/integrations/meta_ads/lib/budget-change"
import {
  parseCreateAdSetArgs,
  createAdSetProblem,
  adSetSummaries,
  type CreateAdSetArgs,
} from "@/integrations/meta_ads/lib/create-ad-set"
import { parseCreateAdsArgs, type CreateAdsArgs } from "@/integrations/meta_ads/lib/create-ads-args"
import { createAdsProblem } from "@/integrations/meta_ads/lib/create-ads-checks"
import {
  editSetting,
  type EditedAds,
  type SharedKey,
} from "@/integrations/meta_ads/lib/create-ads-edits"
import {
  createCampaignProblem,
  parseCreateCampaignArgs,
  type CreateCampaignArgs,
} from "@/integrations/meta_ads/lib/create-campaign"
import { pluralize } from "@/lib/format"
import { isNonEmptyString, isRecord } from "@/lib/guards"

const DAY = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
})
// Fields the campaign and ad set cards read from the launch's own display values.
const ACCOUNT_KEYS = ["_account", "_account_name", "_currency", "_timezone"] as const

type LaunchAdSet = {
  key: string
  args: CreateAdSetArgs
  // The ad set as sent, so edits keep every field the card doesn't change.
  raw: Record<string, unknown>
}

export type LaunchArgs = {
  accountName: string | null
  currency: string | null
  goLive: boolean
  campaign: CreateCampaignArgs
  rawCampaign: Record<string, unknown>
  adSets: LaunchAdSet[]
  // The ads in the shape the Create Ads card reads: ad_sets name the launch's ad set keys.
  ads: CreateAdsArgs
}

/** Reads the launch arguments into the arguments the campaign, ad set, and Create Ads cards take. */
export function parseLaunchArgs(value: unknown): LaunchArgs | null {
  if (!isRecord(value)) return null
  const { campaign, ad_sets: rawAdSets, ads: rawAds } = value
  if (!isRecord(campaign) || !Array.isArray(rawAdSets) || !Array.isArray(rawAds)) return null
  const account = Object.fromEntries(ACCOUNT_KEYS.map((key) => [key, value[key]]))
  const campaignArgs = parseCreateCampaignArgs({
    ...campaign,
    ...account,
    _minimum: value["_minimum"],
    _minimum_spend_limit: value["_minimum_spend_limit"],
  })
  if (!campaignArgs) return null
  const perAdSet = isRecord(value["_ad_set_accounts"]) ? value["_ad_set_accounts"] : {}
  const adSets: LaunchAdSet[] = []
  for (const item of rawAdSets) {
    if (!isRecord(item) || !isNonEmptyString(item["key"])) return null
    const facts = isRecord(perAdSet[item["key"]]) ? perAdSet[item["key"]] : {}
    const args = parseCreateAdSetArgs({
      ...item,
      ...account,
      campaign: campaignFacts(campaign),
      status: "paused",
      _minimum: isRecord(facts) ? facts["minimum"] : null,
      _minimum_goal: isRecord(facts) ? facts["minimum_goal"] : null,
      _eu: isRecord(facts) ? facts["eu"] : null,
    })
    if (!args) return null
    adSets.push({ key: item["key"], args, raw: item })
  }
  const goLive = value["go_live"] === true
  const ads = parseCreateAdsArgs({
    ...value,
    ads: rawAds.map(withAdSetReferences),
    status: goLive ? "active" : "paused",
    _ad_sets: adSetInfo(campaignArgs, adSets),
  })
  if (!ads) return null
  return {
    accountName: campaignArgs.accountName,
    currency: campaignArgs.currency,
    goLive,
    campaign: campaignArgs,
    rawCampaign: campaign,
    adSets,
    ads,
  }
}

/** The campaign as the ad set card reads a hydrated campaign reference. */
function campaignFacts(campaign: Record<string, unknown>): Record<string, unknown> {
  const budget = isRecord(campaign["budget"]) ? campaign["budget"] : {}
  const mode = budget["mode"]
  const categories = Array.isArray(campaign["special_ad_categories"])
    ? campaign["special_ad_categories"]
    : []
  return {
    campaign_id: "launch",
    label: campaign["name"],
    objective: campaign["objective"],
    status: "PAUSED",
    budget:
      (mode === "campaign_daily" || mode === "campaign_lifetime") && budget["amount"]
        ? {
            amount: budget["amount"],
            kind: mode === "campaign_daily" ? "daily" : "lifetime",
          }
        : null,
    bid_strategy: campaign["bid_strategy"],
    share_between_ad_sets: budget["share_between_ad_sets"] === true,
    special_ad_categories: categories.flatMap((item) =>
      isRecord(item) && typeof item["category"] === "string" ? [item["category"].toUpperCase()] : []
    ),
  }
}

/** Stands each ad set key in for the ad set reference a Create Ads design holds. */
function withAdSetReferences(ad: unknown): unknown {
  if (!isRecord(ad)) return ad
  const { ad_set_keys: keys, ...rest } = ad
  return {
    ...rest,
    ad_sets: Array.isArray(keys) ? keys.map((key: unknown) => ({ adset_id: key })) : [],
  }
}

function adSetInfo(campaign: CreateCampaignArgs, adSets: readonly LaunchAdSet[]) {
  return Object.fromEntries(
    adSets.map(({ key, args }) => [
      key,
      { label: args.name, objective: `OUTCOME_${campaign.objective.toUpperCase()}` },
    ])
  )
}

/** The edit for the campaign card: the whole campaign, with what changed. */
export function campaignEdit(
  args: LaunchArgs,
  edits: Record<string, EditedValue>
): Record<string, EditedValue> {
  return { campaign: { ...args.rawCampaign, ...edits } }
}

/** The edit for one ad set card: the whole list, with what changed in that ad set. */
export function adSetEdit(
  args: LaunchArgs,
  key: string,
  edits: Record<string, EditedValue>
): Record<string, EditedValue> {
  return {
    ad_sets: args.adSets.map((item) => (item.key === key ? { ...item.raw, ...edits } : item.raw)),
  }
}

/** The edit for ads changed on the Create Ads editor, back in the launch's own shape. */
export function adsEdit(ads: EditedAds): Record<string, EditedValue> {
  return {
    ads: ads.map((ad) => {
      const { ad_sets: adSets, status: _status, ...rest } = ad
      const keys = Array.isArray(adSets)
        ? adSets.flatMap((item) => (isRecord(item) ? [String(item["adset_id"])] : []))
        : []
      return { ...rest, ad_set_keys: keys }
    }),
  }
}

/** The edit for a link, button, or URL tags: the shared value, or the ad's own once it has one. */
export function launchSettingEdit(
  args: LaunchArgs,
  index: number,
  key: SharedKey,
  value: string | null
): Record<string, EditedValue> {
  const edit = editSetting(args.ads, index, key, value)
  return edit.field === "ads" && Array.isArray(edit.value)
    ? adsEdit(edit.value.filter(isRecord))
    : { [edit.field]: edit.value }
}

/** The ads that go in one ad set. */
function adsIn(args: LaunchArgs, key: string) {
  return args.ads.ads.filter((ad) => ad.adSetIds.includes(key))
}

function cents(amount: string | null): number {
  return amount ? Math.round(Number(amount) * 100) : 0
}

function longDate(value: string): string {
  const parsed = new Date(`${value}T00:00:00Z`)
  return Number.isNaN(parsed.getTime()) ? value : DAY.format(parsed)
}

/** The most the launch can spend, from the campaign budget or the ad set budgets; null until set. */
export function spendLine(args: LaunchArgs): string | null {
  const { campaign, adSets, currency } = args
  const money = (amount: number) => budgetMoney(String(amount / 100), currency)
  const { budget } = campaign
  let daily = 0
  let total = 0
  let ends: string | null = null
  if (budget.mode === "campaign_daily") daily = cents(budget.amount)
  else if (budget.mode === "campaign_lifetime") {
    total = cents(budget.amount)
    ends = campaign.endDate
  } else {
    for (const { args: adSet } of adSets) {
      if (adSet.budget?.kind === "daily") daily += cents(adSet.budget.amount)
      if (adSet.budget?.kind === "lifetime") {
        total += cents(adSet.budget.amount)
        if (adSet.endDate && (!ends || adSet.endDate > ends)) ends = adSet.endDate
      }
    }
  }
  const parts = [
    daily > 0 ? `${money(daily)} a day in total` : null,
    total > 0
      ? `${money(total)} over the whole run${ends ? `, ending ${longDate(ends)}` : ""}`
      : null,
  ].filter(Boolean)
  if (parts.length === 0) return null
  const flexible =
    daily > 0
      ? " Meta may spend up to 75% more on some days, but no more than 7 times this in a week."
      : ""
  return `Up to ${parts.join(" plus ")}.${flexible}`
}

/** One line for an ad set block while it is closed. */
export function adSetBlockSummary(args: LaunchArgs, key: string): string {
  const item = args.adSets.find((candidate) => candidate.key === key)
  const count = adsIn(args, key).length
  const summaries = item ? adSetSummaries(item.args) : null
  return [summaries?.budget, `${String(count)} ${pluralize(count, "ad")}`]
    .filter(Boolean)
    .join(" · ")
}

/** The first thing that stops this ad set's block from being approved, for its header. */
export function adSetProblem(args: LaunchArgs, key: string): string | null {
  const item = args.adSets.find((candidate) => candidate.key === key)
  if (!item) return null
  if (adsIn(args, key).length === 0) return "Add at least one ad to this ad set."
  return createAdSetProblem(item.args)
}

/** Blocks approval for what Meta would refuse, using the same checks as the step cards. */
export function launchProblem(args: LaunchArgs | null): string | null {
  if (!args) return null
  const campaign = createCampaignProblem(args.campaign)
  if (campaign) return campaign
  const names = new Set<string>()
  for (const { key, args: adSet } of args.adSets) {
    const problem = adSetProblem(args, key)
    if (problem) return `${adSet.name || "An ad set"}: ${problem}`
    const name = adSet.name.trim().toLocaleLowerCase()
    if (names.has(name)) return "Give each ad set a different name."
    names.add(name)
  }
  const keys = new Set(args.adSets.map((item) => item.key))
  if (args.ads.ads.some((ad) => ad.adSetIds.some((key) => !keys.has(key))))
    return "An ad is placed in an ad set that isn't part of this launch."
  return createAdsProblem(args.ads)
}

export function launchPrompt(args: LaunchArgs): string {
  const ads = args.ads.ads.reduce((total, ad) => total + ad.adSetIds.length, 0)
  const sets = args.adSets.length
  return `${args.goLive ? "Build and turn on" : "Build, paused,"} ${args.campaign.name} with ${String(sets)} ${pluralize(sets, "ad set")} and ${String(ads)} ${pluralize(ads, "ad")}${args.accountName ? ` in ${args.accountName}` : ""}.`
}
