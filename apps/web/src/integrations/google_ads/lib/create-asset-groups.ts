// apps/web/src/integrations/google_ads/lib/create-asset-groups.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import { collapseSpaces } from "@/integrations/ads/lib/keyword-notation"
import {
  parseApprovalAccounts,
  type GoogleAdsApprovalAccount,
} from "@/integrations/google_ads/lib/accounts"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import {
  parseCampaign,
  parseEach,
  text,
  type CampaignTarget,
} from "@/integrations/google_ads/lib/create-ad-groups"
import {
  assetGroupRows,
  assetGroupsObjectCount,
  parseAssetGroup,
  parsePerformanceMaxChecks,
  serializeAssetGroups,
  type AssetGroupRow,
  type DraftAssetGroup,
  type PerformanceMaxChecks,
} from "@/integrations/google_ads/lib/performance-max"
import { isRecord } from "@/lib/guards"

const MAX_OBJECTS = 2_500

type CampaignCheck = { key: string; name: string; problem: string | null; retail: boolean }

type AssetGroupChecks =
  | { unavailable: true }
  | {
      unavailable: false
      campaign: CampaignCheck
      existingNames: Set<string>
      performanceMax: PerformanceMaxChecks
      requestProblems: string[]
    }

export type CreateAssetGroupsArgs = {
  accounts: Map<string, GoogleAdsApprovalAccount>
  assetGroups: DraftAssetGroup[]
  campaign: CampaignTarget
  checks: AssetGroupChecks
  status: "PAUSED" | "ENABLED"
}

function foldName(name: string): string {
  return collapseSpaces(name).toLowerCase()
}

function parseChecks(value: unknown): AssetGroupChecks {
  if (!isRecord(value) || value["unavailable"] !== false || !isRecord(value["campaign"]))
    return { unavailable: true }
  const campaign = value["campaign"]
  const strings = (item: unknown) =>
    Array.isArray(item) ? item.filter((entry): entry is string => typeof entry === "string") : []
  return {
    unavailable: false,
    campaign: {
      key: text(campaign["key"]),
      name: text(campaign["name"]),
      problem: text(campaign["problem"]) || null,
      retail: campaign["retail"] === true,
    },
    existingNames: new Set(strings(value["existing_names"]).map(foldName)),
    performanceMax: parsePerformanceMaxChecks(value),
    requestProblems: strings(value["request_problems"]),
  }
}

/** Reads the request with the trusted `_accounts` and `_checks`; null when malformed. */
export function parseCreateAssetGroupsArgs(value: unknown): CreateAssetGroupsArgs | null {
  if (!isRecord(value)) return null
  const campaign = parseCampaign(value["campaign"])
  const assetGroups = parseEach(value["asset_groups"], parseAssetGroup)
  const status = value["status"] ?? "PAUSED"
  if (campaign === null || assetGroups === null) return null
  if (status !== "PAUSED" && status !== "ENABLED") return null
  return {
    accounts: parseApprovalAccounts(value["_accounts"]),
    assetGroups,
    campaign,
    checks: parseChecks(value["_checks"]),
    status,
  }
}

/** The campaign's checks, unless the operator has since chosen a different campaign. */
export function campaignCheck(args: CreateAssetGroupsArgs): CampaignCheck | null {
  if (args.checks.unavailable || args.checks.campaign.key !== args.campaign.key) return null
  return args.checks.campaign
}

export function assetGroupChecks(args: CreateAssetGroupsArgs): PerformanceMaxChecks | null {
  return campaignCheck(args) && !args.checks.unavailable ? args.checks.performanceMax : null
}

/** Each asset group with what Google needs before it accepts it, names in the campaign included. */
export function createAssetGroupRows(args: CreateAssetGroupsArgs): AssetGroupRow[] {
  const check = campaignCheck(args)
  const existing = check && !args.checks.unavailable ? args.checks.existingNames : new Set()
  return assetGroupRows(args.assetGroups, {
    checks: assetGroupChecks(args),
    retail: check?.retail ?? false,
  }).map((row) =>
    existing.has(foldName(row.group.name))
      ? {
          ...row,
          problems: ["The campaign already has an asset group by this name.", ...row.problems],
        }
      : row
  )
}

/** Problems with the whole request, not one asset group: the campaign, the size, and Google's. */
export function requestProblems(args: CreateAssetGroupsArgs): string[] {
  const check = campaignCheck(args)
  return [
    ...(check?.problem ? [check.problem] : []),
    ...(assetGroupsObjectCount(args.assetGroups) > MAX_OBJECTS
      ? [`One request can create at most ${MAX_OBJECTS.toLocaleString("en-GB")} objects.`]
      : []),
    ...(check && !args.checks.unavailable ? args.checks.requestProblems : []),
  ]
}

function requestKey(args: CreateAssetGroupsArgs): string {
  return JSON.stringify([args.campaign.reference, serializeAssetGroups(args.assetGroups)])
}

/** True when Google hasn't answered for this request. Status doesn't change its answer. */
export function assetGroupsNeedCheck(
  args: CreateAssetGroupsArgs,
  checked: CreateAssetGroupsArgs
): boolean {
  return args.checks.unavailable || requestKey(args) !== requestKey(checked)
}

export function canCheckAssetGroups(args: CreateAssetGroupsArgs): boolean {
  return (
    args.assetGroups.length > 0 &&
    assetGroupsObjectCount(args.assetGroups) <= MAX_OBJECTS &&
    // Image shapes and whether the campaign has a feed need Google's read, so they don't count.
    assetGroupRows(args.assetGroups, { checks: null, retail: true }).every(
      (row) => row.problems.length === 0
    )
  )
}

/** Why the request can't be approved yet, or null. */
export function createAssetGroupsBlock(
  args: CreateAssetGroupsArgs | null,
  checked: CreateAssetGroupsArgs
): string | null {
  if (args === null) return null
  if (args.assetGroups.length === 0)
    return "Every asset group is cancelled. Decline this request, or restore one."
  const [problem] = requestProblems(args)
  if (problem) return problem
  const failing = createAssetGroupRows(args).filter((row) => row.problems.length > 0).length
  if (failing > 0) return `Fix or cancel ${approvalCountLine(failing, "asset group")} to continue.`
  return assetGroupsNeedCheck(args, checked)
    ? "Click Check Changes so Google can check your edits, then approve."
    : null
}

export function createAssetGroupsPrompt(args: CreateAssetGroupsArgs): string {
  const count = args.assetGroups.length
  if (count === 0) return "Nothing is left to add."
  const name = campaignCheck(args)?.name ?? args.campaign.label
  return `Add ${String(count)} asset group${count === 1 ? "" : "s"} to ${name}.`
}

export function createAssetGroupsApproveLabel(args: CreateAssetGroupsArgs): string {
  const count = args.assetGroups.length
  return count === 0
    ? "Add Asset Groups"
    : `Add ${String(count)} ${count === 1 ? "Asset Group" : "Asset Groups"}`
}

export function createAssetGroupsDetails(args: CreateAssetGroupsArgs | null): FanOutDetail[] {
  if (args === null) return []
  return [
    { label: "Campaign", value: args.campaign.label },
    { label: "Asset Groups", value: String(args.assetGroups.length) },
    { label: "Status", value: args.status === "ENABLED" ? "Active" : "Paused" },
  ]
}
