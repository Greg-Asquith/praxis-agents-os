// apps/web/src/integrations/google_ads/components/create-campaign-approval.tsx

import { useId, useMemo, useState } from "react"

import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-types"
import type { EditedValue } from "@/components/tool-ui/edited-values"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import type { EntityChoice } from "@/features/tools/types"
import { ChangeBanner } from "@/integrations/ads/components/change-banner"
import {
  Chip,
  ChoiceCards,
  SegmentedChoice,
  SelectField,
  SwitchField,
  TextField,
} from "@/integrations/ads/components/controls"
import { EntitySearch } from "@/integrations/ads/components/entity-search"
import { KeywordPaste } from "@/integrations/ads/components/keyword-paste"
import { MoneyField } from "@/integrations/ads/components/money-field"
import { SettingLine, SettingRow, SettingRows } from "@/integrations/ads/components/setting-rows"
import { StatusChoice } from "@/integrations/ads/components/status-choice"
import { CheckChanges } from "@/integrations/google_ads/components/check-changes"
import { LocationPaste } from "@/integrations/google_ads/components/location-paste"
import { NewAssetsEditor } from "@/integrations/google_ads/components/new-assets-editor"
import {
  AdGroupSummary,
  NewAdGroups,
  ProblemList,
} from "@/integrations/google_ads/components/new-ad-groups"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import {
  createAdGroupsCounts,
  keywordMixLine,
  parseCancelledAdGroups,
  serializeAdGroups,
  type DraftAdGroup,
} from "@/integrations/google_ads/lib/create-ad-groups"
import {
  biddingRules,
  biddingSummary,
  budgetSummary,
  campaignAdGroupRows,
  campaignNeedsCheck,
  campaignProblems,
  canCheckCampaign,
  currencyOf,
  dailyBudget,
  locationName,
  money,
  monthlyEstimate,
  PAGE_LOCATION_LABELS,
  PAGE_LOCATIONS,
  requestProblems,
  serializeCampaign,
  STRATEGIES,
  STRATEGY_LABELS,
  type CreateCampaignArgs,
  type DraftBidding,
  type DraftCampaign,
  type DraftLocation,
  type LocationSetting,
  type PageLocation,
  type Strategy,
} from "@/integrations/google_ads/lib/create-campaign"
import { assetSummary, isAssetProblem } from "@/integrations/google_ads/lib/new-assets"

const TOOL_NAME = "google_ads_create_campaign"
// Chips shown per list before Show All, so a long paste doesn't fill the card.
const CHIPS_SHOWN = 12

const STRATEGY_NOTES: Record<Strategy, string> = {
  MANUAL_CPC: "Set each bid yourself.",
  MAXIMIZE_CLICKS: "Get the most visits for the budget.",
  MAXIMIZE_CONVERSIONS: "Get the most conversions for the budget.",
  MAXIMIZE_CONVERSION_VALUE: "Get the most sales value for the budget.",
  TARGET_IMPRESSION_SHARE: "Show at the top of the page.",
}

const WHO_COUNTS: readonly { value: LocationSetting; label: string; description: string }[] = [
  {
    value: "PRESENCE",
    label: "People in your locations",
    description: "People who are in, or regularly in, the places you target.",
  },
  {
    value: "PRESENCE_OR_INTEREST",
    label: "People in or interested in your locations",
    description: "Also people searching for, or showing interest in, those places.",
  },
]

export function CreateCampaignApproval({
  args,
  checked,
  controls,
  disabled,
  onFieldEdit,
}: {
  args: CreateCampaignArgs
  // The request Google last answered for.
  checked: CreateCampaignArgs
  controls: ToolApprovalDecisionControls
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
}) {
  const rows = useMemo(() => campaignAdGroupRows(args), [args])
  const counts = createAdGroupsCounts(rows)
  // Cancelled ad groups, so Restore puts them back with their edits.
  const cancelled = parseCancelledAdGroups(controls.retained, args.adGroups)
  const { campaign } = args

  const editCampaign = (patch: Partial<DraftCampaign>) => {
    onFieldEdit("campaign", serializeCampaign({ ...campaign, ...patch }))
  }
  const saveAdGroups = (adGroups: readonly DraftAdGroup[]) => {
    onFieldEdit("ad_groups", serializeAdGroups(adGroups))
  }
  const cancel = (indexes: ReadonlySet<number>) => {
    controls.onRetain?.(
      serializeAdGroups([...cancelled, ...args.adGroups.filter((_, at) => indexes.has(at))])
    )
    saveAdGroups(args.adGroups.filter((_, at) => !indexes.has(at)))
  }
  const restore = () => {
    saveAdGroups([...args.adGroups, ...cancelled])
    controls.onRetain?.([])
  }

  return (
    <div className="grid min-w-0 gap-3">
      <SpendBanner args={args} />
      <StatusChoice
        activeNote="Active, pending approval. Will go live once approved by Google."
        disabled={disabled}
        onChange={(status) => {
          onFieldEdit("status", status === "active" ? "ENABLED" : "PAUSED")
        }}
        pausedNote="Paused. Will not appear or spend until activated."
        value={args.status === "ENABLED" ? "active" : "paused"}
      />
      <ProblemList problems={[...requestProblems(args), ...campaignProblems(args)]} />
      <CampaignSettings args={args} disabled={disabled} onEdit={editCampaign} />
      <p className="text-sm font-medium">Ad Groups</p>
      {rows.length > 1 || cancelled.length > 0 ? (
        <AdGroupSummary
          cancelled={cancelled.length}
          counts={counts}
          detail="in this campaign"
          disabled={disabled}
          keywordMix={keywordMixLine(rows)}
          onCancelProblems={() => {
            cancel(new Set(rows.filter((row) => row.problems.length > 0).map((row) => row.index)))
          }}
          onRestore={restore}
        />
      ) : null}
      <NewAdGroups
        currency={currencyOf(args)}
        disabled={disabled}
        onCancel={cancel}
        onSave={saveAdGroups}
        rows={rows}
        rules={biddingRules(campaign.bidding)}
      />
      {/* At the end, beside the approve button that waits on it. */}
      {campaignNeedsCheck(args, checked) ? (
        <CheckChanges
          canCheck={canCheckCampaign(args)}
          disabled={disabled}
          label={args.checks.unavailable ? "Check Again" : "Check Changes"}
          note="Google hasn't checked these changes yet."
          onCheck={controls.onReview}
          submitting={controls.submitting}
        />
      ) : null}
    </div>
  )
}

/** States the daily budget and about what a month costs, once there's an amount. */
function SpendBanner({ args }: { args: CreateCampaignArgs }) {
  const daily = dailyBudget(args.campaign)
  const monthly = monthlyEstimate(args.campaign)
  if (daily === null || monthly === null) return null
  const timeZone = [...args.accounts.values()][0]?.timeZone
  return (
    <ChangeBanner
      aside={
        <div className="text-right">
          <p className="text-lg font-semibold tabular-nums">{money(monthly, args)}</p>
          <p className="text-muted-foreground text-xs">about a month</p>
        </div>
      }
      detail={[`${money(daily, args)} a day`, timeZone ? `Account time ${timeZone}` : null]
        .filter(Boolean)
        .join(" · ")}
      title={
        args.status === "ENABLED" ? "Spends Once Google Approves the Ads" : "Spend Once Turned On"
      }
    />
  )
}

function CampaignSettings({
  args,
  disabled,
  onEdit,
}: {
  args: CreateCampaignArgs
  disabled: boolean
  onEdit: (patch: Partial<DraftCampaign>) => void
}) {
  const nameId = useId()
  const { campaign } = args
  return (
    <SettingRows ariaLabel="Campaign settings">
      <SettingLine htmlFor={nameId} title="Name">
        <Input
          className="text-sm"
          disabled={disabled}
          id={nameId}
          onChange={(event) => {
            onEdit({ name: event.currentTarget.value })
          }}
          value={campaign.name}
        />
      </SettingLine>
      <SettingRow rowKey="budget" summary={budgetSummary(args)} title="Budget">
        <BudgetFields args={args} disabled={disabled} onEdit={onEdit} />
      </SettingRow>
      <SettingRow rowKey="bidding" summary={biddingSummary(args)} title="Bidding">
        <BiddingFields
          bidding={campaign.bidding}
          currency={currencyOf(args)}
          disabled={disabled}
          onEdit={(patch) => {
            onEdit({ bidding: { ...campaign.bidding, ...patch } })
          }}
        />
      </SettingRow>
      <SettingRow
        rowKey="locations"
        summary={locationSummary(args)}
        title="Locations"
        tone={campaign.locations.length === 0 ? "error" : "neutral"}
      >
        <LocationFields args={args} disabled={disabled} onEdit={onEdit} />
      </SettingRow>
      <SettingRow
        rowKey="more"
        summary={moreSummary(campaign)}
        title="More Settings"
        tone={campaignProblems(args).some(isAssetProblem) ? "error" : "neutral"}
      >
        <MoreFields campaign={campaign} disabled={disabled} onEdit={onEdit} />
      </SettingRow>
    </SettingRows>
  )
}

function BudgetFields({
  args,
  disabled,
  onEdit,
}: {
  args: CreateCampaignArgs
  disabled: boolean
  onEdit: (patch: Partial<DraftCampaign>) => void
}) {
  const [searching, setSearching] = useState(false)
  const { budget } = args.campaign
  if (budget.kind === "shared") {
    return (
      <div className="grid gap-2">
        <p className="text-sm">
          Spends from the shared budget {budget.label}
          {budget.dailyAmount ? `, ${money(budget.dailyAmount, args)} a day` : ""}, with the other
          campaigns that use it.
        </p>
        <Button
          className="w-fit"
          disabled={disabled}
          onClick={() => {
            onEdit({ budget: { kind: "new", dailyAmount: budget.dailyAmount ?? "" } })
          }}
          size="sm"
          type="button"
          variant="outline"
        >
          Give It Its Own Budget
        </Button>
      </div>
    )
  }
  return (
    <div className="grid gap-3">
      <MoneyField
        className="max-w-60"
        currency={currencyOf(args)}
        disabled={disabled}
        label="Daily Budget"
        onChange={(dailyAmount) => {
          onEdit({ budget: { kind: "new", dailyAmount } })
        }}
        suffix="a day"
        value={budget.dailyAmount}
      />
      {searching ? (
        <EntitySearch
          disabled={disabled}
          entityKind="google_ads_campaign_budget"
          fieldKey="campaign"
          label="Search shared budgets"
          onChoose={(choice) => {
            onEdit({ budget: sharedBudget(choice) })
            setSearching(false)
          }}
          toolName={TOOL_NAME}
        />
      ) : (
        <Button
          className="w-fit"
          disabled={disabled}
          onClick={() => {
            setSearching(true)
          }}
          size="sm"
          type="button"
          variant="ghost"
        >
          Use a Shared Budget
        </Button>
      )}
    </div>
  )
}

function sharedBudget(choice: EntityChoice): DraftCampaign["budget"] {
  const micros = choice.value["amount_micros"]
  const shared = choice.value["explicitly_shared"]
  return {
    dailyAmount:
      typeof micros === "string" && /^\d+$/.test(micros) ? String(Number(micros) / 1e6) : null,
    kind: "shared",
    label: choice.label,
    reference: choice.value,
    shared: typeof shared === "boolean" ? shared : null,
  }
}

function BiddingFields({
  bidding,
  currency,
  disabled,
  onEdit,
}: {
  bidding: DraftBidding
  currency: string | null
  disabled: boolean
  onEdit: (patch: Partial<DraftBidding>) => void
}) {
  const shareId = useId()
  return (
    <div className="grid gap-3">
      <ChoiceCards
        ariaLabel="Bidding"
        columns={2}
        disabled={disabled}
        onChange={(strategy) => {
          if (STRATEGIES.includes(strategy as Strategy)) onEdit({ strategy: strategy as Strategy })
        }}
        options={STRATEGIES.map((strategy) => ({
          value: strategy,
          label: STRATEGY_LABELS[strategy],
          description: STRATEGY_NOTES[strategy],
        }))}
        value={bidding.strategy}
      />
      {bidding.strategy === "MAXIMIZE_CONVERSIONS" ? (
        <MoneyField
          className="max-w-60"
          currency={currency}
          disabled={disabled}
          label="Target CPA (Optional)"
          onChange={(targetCpa) => {
            onEdit({ targetCpa })
          }}
          value={bidding.targetCpa}
        />
      ) : null}
      {bidding.strategy === "MAXIMIZE_CONVERSION_VALUE" ? (
        <TextField
          disabled={disabled}
          inputMode="decimal"
          label="Target ROAS % (Optional)"
          onChange={(targetRoas) => {
            onEdit({ targetRoas: targetRoas.trim() })
          }}
          placeholder="350"
          value={bidding.targetRoas}
        />
      ) : null}
      {bidding.strategy === "TARGET_IMPRESSION_SHARE" ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <SelectField
            disabled={disabled}
            label="Where on the Page"
            onChange={(pageLocation) => {
              if (PAGE_LOCATIONS.includes(pageLocation as PageLocation))
                onEdit({ pageLocation: pageLocation as PageLocation })
            }}
            options={PAGE_LOCATIONS.map((value) => ({
              value,
              label: PAGE_LOCATION_LABELS[value],
            }))}
            value={bidding.pageLocation}
          />
          <div className="grid min-w-0 gap-1">
            <label className="text-sm font-medium" htmlFor={shareId}>
              Share of Searches (%)
            </label>
            <Input
              className="text-sm tabular-nums"
              disabled={disabled}
              id={shareId}
              inputMode="numeric"
              onChange={(event) => {
                onEdit({ sharePercent: event.currentTarget.value.trim() })
              }}
              value={bidding.sharePercent}
            />
          </div>
        </div>
      ) : null}
      {bidding.strategy === "MAXIMIZE_CLICKS" || bidding.strategy === "TARGET_IMPRESSION_SHARE" ? (
        <MoneyField
          className="max-w-60"
          currency={currency}
          disabled={disabled}
          label={
            bidding.strategy === "MAXIMIZE_CLICKS"
              ? "Maximum Click Bid (Optional)"
              : "Maximum Click Bid"
          }
          onChange={(maxCpc) => {
            onEdit({ maxCpc })
          }}
          value={bidding.maxCpc}
        />
      ) : null}
    </div>
  )
}

function locationSummary(args: CreateCampaignArgs): string {
  const { campaign } = args
  const [first] = campaign.locations
  if (!first) return "No locations"
  const more = campaign.locations.length - 1
  const excluded = campaign.excludedLocations.length
  return [
    more > 0 ? `${locationName(first, args)} and ${String(more)} more` : locationName(first, args),
    excluded > 0 ? `excluding ${approvalCountLine(excluded, "place")}` : null,
    campaign.locationSetting === "PRESENCE"
      ? "People in the area"
      : "People in or interested in the area",
  ]
    .filter(Boolean)
    .join(" · ")
}

type LocationField = "locations" | "excludedLocations"

function choiceLocation(choice: EntityChoice): DraftLocation | null {
  const key = choice.value["key"]
  return typeof key === "string" && /^\d+$/.test(key) ? { key, name: choice.label } : null
}

function LocationFields({
  args,
  disabled,
  onEdit,
}: {
  args: CreateCampaignArgs
  disabled: boolean
  onEdit: (patch: Partial<DraftCampaign>) => void
}) {
  const { campaign } = args
  const [field, setField] = useState<LocationField>("locations")
  const taken = new Set(
    [...campaign.locations, ...campaign.excludedLocations].map((item) => item.key)
  )
  const add = (choices: readonly EntityChoice[]) => {
    const added = choices.flatMap((choice) => {
      const location = choiceLocation(choice)
      if (location === null || taken.has(location.key)) return []
      taken.add(location.key)
      return [location]
    })
    if (added.length > 0) onEdit({ [field]: [...campaign[field], ...added] })
  }
  const remove = (list: LocationField, key: string) => {
    onEdit({ [list]: campaign[list].filter((item) => item.key !== key) })
  }
  return (
    <div className="grid min-w-0 gap-3">
      <LocationChips
        args={args}
        disabled={disabled}
        label="Shows Ads In"
        locations={campaign.locations}
        onRemove={(key) => {
          remove("locations", key)
        }}
      />
      <LocationChips
        args={args}
        disabled={disabled}
        label="Doesn't Show Ads In"
        locations={campaign.excludedLocations}
        onRemove={(key) => {
          remove("excludedLocations", key)
        }}
      />
      <Tabs className="min-w-0 rounded-lg border p-3" defaultValue="search">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <TabsList>
            <TabsTrigger value="search">Search</TabsTrigger>
            <TabsTrigger value="paste">Paste a List</TabsTrigger>
          </TabsList>
          <SegmentedChoice
            ariaLabel="What to do with this location"
            disabled={disabled}
            onChange={setField}
            options={[
              { label: "Show Ads", value: "locations" },
              { label: "Don't Show Ads", value: "excludedLocations" },
            ]}
            value={field}
          />
        </div>
        <TabsContent className="pt-3" value="search">
          <EntitySearch
            disabled={disabled}
            entityKind="google_ads_location"
            fieldKey="campaign"
            isTaken={(choice) => taken.has(String(choice.value["key"]))}
            label="Search for a location"
            onChoose={(choice) => {
              add([choice])
            }}
            placeholder="Search cities, regions, or postcodes"
            searchRequired
            toolName={TOOL_NAME}
          />
        </TabsContent>
        <TabsContent className="pt-3" value="paste">
          <LocationPaste
            disabled={disabled}
            fieldKey="campaign"
            onFound={add}
            toolName={TOOL_NAME}
          />
        </TabsContent>
      </Tabs>
      <div className="grid gap-1.5">
        <p className="text-sm font-medium">Who Counts</p>
        <ChoiceCards
          ariaLabel="Who counts as in a location"
          disabled={disabled}
          onChange={(value) => {
            if (value === "PRESENCE" || value === "PRESENCE_OR_INTEREST")
              onEdit({ locationSetting: value })
          }}
          options={WHO_COUNTS}
          value={campaign.locationSetting}
        />
      </div>
    </div>
  )
}

function LocationChips({
  args,
  disabled,
  label,
  locations,
  onRemove,
}: {
  args: CreateCampaignArgs
  disabled: boolean
  label: string
  locations: readonly DraftLocation[]
  onRemove: (key: string) => void
}) {
  const [all, setAll] = useState(false)
  if (locations.length === 0) return null
  const shown = all ? locations : locations.slice(0, CHIPS_SHOWN)
  return (
    <div className="grid min-w-0 gap-1.5">
      <p className="text-sm font-medium">
        {label} <span className="text-muted-foreground tabular-nums">{locations.length}</span>
      </p>
      <div className="flex min-w-0 flex-wrap gap-1.5">
        {shown.map((location) => (
          <Chip
            key={location.key}
            disabled={disabled}
            label={locationName(location, args)}
            onRemove={() => {
              onRemove(location.key)
            }}
          />
        ))}
        {locations.length > shown.length ? (
          <Button
            onClick={() => {
              setAll(true)
            }}
            size="sm"
            type="button"
            variant="ghost"
          >
            Show All {String(locations.length)}
          </Button>
        ) : null}
      </div>
    </div>
  )
}

function moreSummary(campaign: DraftCampaign): string {
  const networks =
    campaign.searchPartners || campaign.displayExpansion
      ? [
          "Search",
          campaign.searchPartners ? "partners" : null,
          campaign.displayExpansion ? "Display" : null,
        ]
          .filter(Boolean)
          .join(", ")
      : "Search only"
  const start = campaign.startDate.trim() ? `starts ${campaign.startDate.trim()}` : "starts when on"
  const end = campaign.endDate.trim() ? `ends ${campaign.endDate.trim()}` : "no end date"
  return [
    networks,
    `${start}, ${end}`,
    campaign.political ? "EU political ads" : "not political",
    campaign.negatives.length > 0 ? approvalCountLine(campaign.negatives.length, "negative") : null,
    campaign.assets.length > 0 ? assetSummary(campaign.assets) : null,
  ]
    .filter(Boolean)
    .join(" · ")
}

function MoreFields({
  campaign,
  disabled,
  onEdit,
}: {
  campaign: DraftCampaign
  disabled: boolean
  onEdit: (patch: Partial<DraftCampaign>) => void
}) {
  return (
    <div className="grid min-w-0 gap-4">
      <div className="grid gap-3">
        <SwitchField
          checked={campaign.searchPartners}
          description="Also show ads on sites that partner with Google Search."
          disabled={disabled}
          label="Search Partners"
          onChange={(searchPartners) => {
            onEdit({ searchPartners })
          }}
        />
        <SwitchField
          checked={campaign.displayExpansion}
          description="Also show ads on websites and apps when that's likely to get results."
          disabled={disabled}
          label="Display Expansion"
          onChange={(displayExpansion) => {
            onEdit({ displayExpansion })
          }}
        />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <TextField
          disabled={disabled}
          label="Start Date (Optional)"
          onChange={(startDate) => {
            onEdit({ startDate })
          }}
          type="date"
          value={campaign.startDate}
        />
        <TextField
          disabled={disabled}
          label="End Date (Optional)"
          onChange={(endDate) => {
            onEdit({ endDate })
          }}
          type="date"
          value={campaign.endDate}
        />
      </div>
      <SwitchField
        checked={campaign.political}
        description="Turn on only if the ads are political and aimed at people in the EU. Google won't show them in the EU."
        disabled={disabled}
        label="EU Political Ads"
        onChange={(political) => {
          onEdit({ political })
        }}
      />
      <KeywordPaste
        disabled={disabled}
        keywords={campaign.negatives}
        label="Negative Keywords for Every Ad Group, One Per Line"
        onChange={(negatives) => {
          onEdit({ negatives })
        }}
      />
      <div className="grid min-w-0 gap-1.5">
        <p className="text-sm font-medium">Sitelinks and Callouts for Every Ad Group</p>
        <NewAssetsEditor
          assets={campaign.assets}
          disabled={disabled}
          onChange={(assets) => {
            onEdit({ assets })
          }}
        />
      </div>
    </div>
  )
}
