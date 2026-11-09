// apps/web/src/integrations/google_ads/components/create-ad-groups-approval.tsx

import { ChevronLeftIcon, ChevronRightIcon, InfoIcon, PlusIcon, XIcon } from "lucide-react"
import { useId, useMemo, useState } from "react"

import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-types"
import type { EditedValue } from "@/components/tool-ui/edited-values"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  DataTable,
  type DataColumn,
  type DataRow,
  type DataTableTab,
} from "@/components/ui/data-table"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { AttentionLine } from "@/integrations/ads/components/attention-line"
import { ChangeSummary, type ChangeSummaryLine } from "@/integrations/ads/components/change-summary"
import { SegmentedChoice } from "@/integrations/ads/components/controls"
import { EntityPicker } from "@/integrations/ads/components/entity-picker"
import { KeywordPaste } from "@/integrations/ads/components/keyword-paste"
import { MoneyField } from "@/integrations/ads/components/money-field"
import { SettingLine, SettingRow, SettingRows } from "@/integrations/ads/components/setting-rows"
import { StatusChoice } from "@/integrations/ads/components/status-choice"
import type { KeywordMatchType } from "@/integrations/ads/lib/keyword-notation"
import { AdCopyEditor } from "@/integrations/google_ads/components/ad-copy-editor"
import { CheckChanges } from "@/integrations/google_ads/components/check-changes"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import {
  adGroupRows,
  adGroupsNeedCheck,
  blankAd,
  campaignCheck,
  canCheckAdGroups,
  createAdGroupsCounts,
  keywordMixLine,
  MAX_ADS,
  mergePastedKeywords,
  parseCampaign,
  parseCancelledAdGroups,
  requestProblems,
  serializeAdGroups,
  type AdGroupRow,
  type CreateAdGroupsArgs,
  type DraftAdGroup,
  type DraftKeyword,
} from "@/integrations/google_ads/lib/create-ad-groups"

const TOOL_NAME = "google_ads_create_ad_groups"
// Below this many rows the table's search only adds noise.
const SEARCH_FROM = 10
const MATCH_TYPES: readonly { value: KeywordMatchType; label: string }[] = [
  { value: "PHRASE", label: "Phrase" },
  { value: "EXACT", label: "Exact" },
  { value: "BROAD", label: "Broad" },
]

const COLUMNS: DataColumn[] = [
  { key: "name", kind: "text", label: "Ad Group", width: 320 },
  { key: "keywords", kind: "number", label: "Keywords", width: 90 },
  { key: "ads", kind: "number", label: "Ads", width: 60 },
  { key: "negatives", kind: "number", label: "Negatives", width: 90 },
  { key: "cancel", kind: "text", label: "Cancel", width: 70 },
]

const TABS: DataTableTab[] = [
  { id: "all", label: "All", match: () => true },
  {
    id: "attention",
    label: "Needs Attention",
    hideWhenEmpty: true,
    match: (row) => row["attention"] === "yes",
  },
]

export function CreateAdGroupsApproval({
  args,
  checked,
  controls,
  disabled,
  onFieldEdit,
}: {
  args: CreateAdGroupsArgs
  // The request Google last answered for.
  checked: CreateAdGroupsArgs
  controls: ToolApprovalDecisionControls
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
}) {
  const rows = useMemo(() => adGroupRows(args), [args])
  const counts = createAdGroupsCounts(rows)
  const [tab, setTab] = useState("all")
  const [open, setOpen] = useState(() => firstToOpen(rows))
  // Cancelled ad groups, so Restore puts them back with their edits.
  const cancelled = parseCancelledAdGroups(controls.retained)
  const openRow = rows[Math.min(open, rows.length - 1)]
  const many = rows.length > 1

  const save = (adGroups: readonly DraftAdGroup[]) => {
    onFieldEdit("ad_groups", serializeAdGroups(adGroups))
  }
  const edit = (index: number, patch: Partial<DraftAdGroup>) => {
    save(args.adGroups.map((group, at) => (at === index ? { ...group, ...patch } : group)))
  }
  const cancel = (indexes: ReadonlySet<number>) => {
    controls.onRetain?.(
      serializeAdGroups([...cancelled, ...args.adGroups.filter((_, at) => indexes.has(at))])
    )
    save(args.adGroups.filter((_, at) => !indexes.has(at)))
    setOpen(0)
  }
  const restore = () => {
    save([...args.adGroups, ...cancelled])
    controls.onRetain?.([])
  }

  const tableRows = useMemo<DataRow[]>(
    () =>
      rows.map((row) => ({
        ads: row.adGroup.ads.length,
        attention: row.problems.length > 0 ? "yes" : "no",
        cancel: "",
        key: String(row.index),
        keywords: row.adGroup.keywords.length,
        name: row.adGroup.name,
        negatives: row.adGroup.negatives.length,
      })),
    [rows]
  )
  const wholeRequest = requestProblems(args)

  return (
    <div className="grid min-w-0 gap-3">
      <BiddingNote args={args} />
      <StatusChoice
        activeNote="Active, pending approval. Will go live once approved by Google."
        disabled={disabled}
        onChange={(status) => {
          onFieldEdit("status", status === "active" ? "ENABLED" : "PAUSED")
        }}
        pausedNote="Paused. Will not appear or spend until activated."
        value={args.status === "ENABLED" ? "active" : "paused"}
      />
      {adGroupsNeedCheck(args, checked) ? (
        <CheckChanges
          canCheck={canCheckAdGroups(args)}
          disabled={disabled}
          label={args.checks.unavailable ? "Check Again" : "Check Changes"}
          note="Google hasn't checked these changes yet."
          onCheck={controls.onReview}
          submitting={controls.submitting}
        />
      ) : null}
      <EntityPicker
        currentLabel={args.campaign.label}
        disabled={disabled}
        fieldKey="campaign"
        label="Campaign"
        onChoose={(reference) => {
          if (parseCampaign(reference)) onFieldEdit("campaign", reference)
        }}
        toolName={TOOL_NAME}
      />
      {wholeRequest.length > 0 ? (
        <ul className="text-destructive grid gap-0.5 text-sm" role="alert">
          {wholeRequest.map((problem) => (
            <li key={problem} className="wrap-anywhere">
              {problem}
            </li>
          ))}
        </ul>
      ) : null}
      {many || cancelled.length > 0 ? (
        <ChangeSummary
          lines={summaryLines({
            campaign: args.campaign.label,
            cancelled: cancelled.length,
            counts,
            disabled,
            keywordMix: keywordMixLine(rows),
            onCancelProblems: () => {
              cancel(new Set(rows.filter((row) => row.problems.length > 0).map((row) => row.index)))
            },
            onRestore: restore,
          })}
        />
      ) : null}
      <AttentionLine
        count={counts.problems}
        onShow={() => {
          setTab("attention")
          setOpen(firstToOpen(rows))
        }}
      />
      {many ? (
        <DataTable
          activeTab={tab}
          columns={COLUMNS}
          exportFilename="google-ads-new-ad-groups.csv"
          onRowClick={(row) => {
            setOpen(Number(row["key"]))
          }}
          onTabChange={setTab}
          pageSize={25}
          renderCell={(column, row) => {
            const adGroupRow = rows[Number(row["key"])]
            if (!adGroupRow) return null
            if (column.key === "name")
              return (
                <span className="grid min-w-0 gap-0.5 whitespace-normal">
                  <CommittedInput
                    ariaLabel="Ad group name"
                    disabled={disabled}
                    onCommit={(name) => {
                      edit(adGroupRow.index, { name })
                    }}
                    value={adGroupRow.adGroup.name}
                  />
                  {adGroupRow.problems[0] ? (
                    <span className="text-destructive text-xs wrap-anywhere">
                      {adGroupRow.problems[0]}
                    </span>
                  ) : null}
                </span>
              )
            if (column.key === "cancel")
              return (
                <Button
                  aria-label={`Cancel ${adGroupRow.adGroup.name}`}
                  disabled={disabled}
                  onClick={(event) => {
                    // The row opens the ad group on click; cancelling shouldn't.
                    event.stopPropagation()
                    cancel(new Set([adGroupRow.index]))
                  }}
                  size="icon-xs"
                  title="Cancel This Change"
                  type="button"
                  variant="ghost"
                >
                  <XIcon />
                </Button>
              )
            return null
          }}
          rowClassName={(row) =>
            Number(row["key"]) === openRow?.index
              ? "bg-muted/70 shadow-[inset_3px_0_0_var(--primary)]"
              : undefined
          }
          rowNoun={["ad group", "ad groups"]}
          rows={tableRows}
          searchable={rows.length >= SEARCH_FROM}
          tabs={TABS}
        />
      ) : null}
      {openRow ? (
        <AdGroupEditor
          key={openRow.index}
          args={args}
          disabled={disabled}
          onEdit={(patch) => {
            edit(openRow.index, patch)
          }}
          position={many ? { total: rows.length, onOpen: setOpen } : null}
          row={openRow}
        />
      ) : null}
    </div>
  )
}

function firstToOpen(rows: readonly AdGroupRow[]): number {
  return rows.find((row) => row.problems.length > 0)?.index ?? 0
}

/** Says once what the campaign's bidding means for these ad groups, or that it's unchecked. */
function BiddingNote({ args }: { args: CreateAdGroupsArgs }) {
  if (args.checks.unavailable) return null
  const check = campaignCheck(args)
  if (check === null) {
    return (
      <Alert role="note">
        <InfoIcon aria-hidden="true" />
        <AlertTitle>{args.campaign.label} Hasn't Been Checked</AlertTitle>
        <AlertDescription>
          Check these changes to see the campaign's bidding and whether its ad group names are free.
        </AlertDescription>
      </Alert>
    )
  }
  if (check.strategyName === null) return null
  return (
    <Alert role="note">
      <InfoIcon aria-hidden="true" />
      <AlertTitle>Campaign Uses {check.strategyName}</AlertTitle>
      <AlertDescription>
        {check.acceptsCpcBid
          ? "Each ad group can have its own click bid, and keywords can override it."
          : "Google sets bids, so these ad groups don't need their own click bids."}
      </AlertDescription>
    </Alert>
  )
}

function summaryLines({
  campaign,
  cancelled,
  counts,
  disabled,
  keywordMix,
  onCancelProblems,
  onRestore,
}: {
  campaign: string
  cancelled: number
  counts: ReturnType<typeof createAdGroupsCounts>
  disabled: boolean
  keywordMix: string
  onCancelProblems: () => void
  onRestore: () => void
}): ChangeSummaryLine[] {
  return [
    {
      id: "ad_groups",
      label: "Ad Groups",
      detail: `in ${campaign}`,
      count: counts.adGroups,
    },
    { id: "keywords", label: "Keywords", detail: keywordMix, count: counts.keywords },
    { id: "ads", label: "Ads", count: counts.ads },
    { id: "negatives", label: "Negative Keywords", count: counts.negatives },
    {
      id: "attention",
      label: "Needs Attention",
      count: counts.problems,
      tone: "danger",
      action: (
        <Button
          disabled={disabled}
          onClick={onCancelProblems}
          size="sm"
          type="button"
          variant="outline"
        >
          Cancel These {String(counts.problems)}
        </Button>
      ),
    },
    {
      id: "cancelled",
      label: "Cancelled",
      count: cancelled,
      action: (
        <Button disabled={disabled} onClick={onRestore} size="sm" type="button" variant="outline">
          Restore
        </Button>
      ),
    },
  ]
}

/** A table cell input that edits on leaving the field, so typing doesn't redraw the whole table. */
function CommittedInput({
  ariaLabel,
  className,
  disabled,
  onCommit,
  placeholder,
  value,
}: {
  ariaLabel: string
  className?: string
  disabled: boolean
  onCommit: (value: string) => void
  placeholder?: string
  value: string
}) {
  return (
    <Input
      key={value}
      aria-label={ariaLabel}
      className={className ?? "h-7 text-sm"}
      defaultValue={value}
      disabled={disabled}
      onBlur={(event) => {
        if (event.currentTarget.value !== value) onCommit(event.currentTarget.value)
      }}
      onClick={(event) => {
        event.stopPropagation()
      }}
      onKeyDown={(event) => {
        // The row opens on Enter and Space, which also need to reach this field as text.
        event.stopPropagation()
      }}
      placeholder={placeholder}
    />
  )
}

function AdGroupEditor({
  args,
  disabled,
  onEdit,
  position,
  row,
}: {
  args: CreateAdGroupsArgs
  disabled: boolean
  onEdit: (patch: Partial<DraftAdGroup>) => void
  // Set when the card has more than one ad group, to say which this is and step between them.
  position: { total: number; onOpen: (index: number) => void } | null
  row: AdGroupRow
}) {
  const { adGroup } = row
  const nameId = useId()
  const currency = [...args.accounts.values()][0]?.currencyCode ?? null
  const check = campaignCheck(args)
  const mix = keywordMixLine([row])
  const adProblems = row.problems.filter((problem) => /^Ad \d/.test(problem))
  return (
    <section
      aria-label={adGroup.name || "Ad group"}
      className="grid min-w-0 gap-3 rounded-lg border px-3 py-3"
    >
      {position ? (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm font-medium">
            Ad Group {String(row.index + 1)} of {String(position.total)}
          </p>
          <span className="flex gap-1">
            <Button
              disabled={row.index === 0}
              onClick={() => {
                position.onOpen(row.index - 1)
              }}
              size="sm"
              type="button"
              variant="ghost"
            >
              <ChevronLeftIcon />
              Previous
            </Button>
            <Button
              disabled={row.index >= position.total - 1}
              onClick={() => {
                position.onOpen(row.index + 1)
              }}
              size="sm"
              type="button"
              variant="ghost"
            >
              Next
              <ChevronRightIcon />
            </Button>
          </span>
        </div>
      ) : null}
      {row.problems.length > 0 ? (
        <ul className="text-destructive grid gap-0.5 text-sm" role="alert">
          {row.problems.map((problem) => (
            <li key={problem} className="wrap-anywhere">
              {problem}
            </li>
          ))}
        </ul>
      ) : null}
      <SettingRows ariaLabel={`${adGroup.name} settings`} defaultOpen="keywords">
        <SettingLine htmlFor={nameId} title="Name">
          <Input
            className="text-sm"
            disabled={disabled}
            id={nameId}
            onChange={(event) => {
              onEdit({ name: event.currentTarget.value })
            }}
            value={adGroup.name}
          />
        </SettingLine>
        <SettingRow
          rowKey="keywords"
          summary={
            adGroup.keywords.length === 0
              ? "No keywords"
              : `${approvalCountLine(adGroup.keywords.length, "keyword")} · ${mix}`
          }
          title="Keywords"
        >
          <KeywordPaste
            disabled={disabled}
            keywords={adGroup.keywords}
            label="Keywords, One Per Line"
            onChange={(pasted) => {
              onEdit({ keywords: mergePastedKeywords(pasted, adGroup.keywords) })
            }}
          />
          <KeywordReview
            acceptsBids={check?.acceptsCpcBid ?? true}
            disabled={disabled}
            keywords={adGroup.keywords}
            onChange={(keywords) => {
              onEdit({ keywords })
            }}
          />
        </SettingRow>
        <SettingRow
          rowKey="ads"
          summary={
            adGroup.ads.length === 0
              ? "No ads"
              : `${approvalCountLine(adGroup.ads.length, "ad")} · ${adProblems.length > 0 ? "needs attention" : "ready"}`
          }
          title="Ads"
          tone={adProblems.length > 0 ? "error" : "neutral"}
        >
          <AdsEditor
            ads={adGroup.ads}
            disabled={disabled}
            onChange={(ads) => {
              onEdit({ ads })
            }}
          />
        </SettingRow>
        <SettingRow
          rowKey="negatives"
          summary={
            adGroup.negatives.length === 0
              ? "No negative keywords"
              : approvalCountLine(adGroup.negatives.length, "negative keyword")
          }
          title="Negatives"
        >
          <KeywordPaste
            disabled={disabled}
            keywords={adGroup.negatives}
            label="Negative Keywords, One Per Line"
            onChange={(negatives) => {
              onEdit({ negatives })
            }}
          />
        </SettingRow>
        <SettingRow rowKey="bids" summary={bidSummary(adGroup)} title="Bids">
          <BidFields
            acceptsCpa={check?.acceptsTargetCpa ?? true}
            acceptsCpc={check?.acceptsCpcBid ?? true}
            acceptsRoas={check?.acceptsTargetRoas ?? true}
            adGroup={adGroup}
            currency={currency}
            disabled={disabled}
            onEdit={onEdit}
          />
        </SettingRow>
      </SettingRows>
    </section>
  )
}

function bidSummary(group: DraftAdGroup): string {
  const parts = [
    group.cpcBid.trim() ? `Click bid ${group.cpcBid.trim()}` : null,
    group.targetCpa.trim() ? `Target CPA ${group.targetCpa.trim()}` : null,
    group.targetRoas.trim() ? `Target ROAS ${group.targetRoas.trim()}%` : null,
  ].filter(Boolean)
  return parts.join(" · ") || "Uses the campaign's bidding"
}

/** Each override the campaign can use, plus any it can't that is set, so it can be cleared. */
function BidFields({
  acceptsCpa,
  acceptsCpc,
  acceptsRoas,
  adGroup,
  currency,
  disabled,
  onEdit,
}: {
  acceptsCpa: boolean
  acceptsCpc: boolean
  acceptsRoas: boolean
  adGroup: DraftAdGroup
  currency: string | null
  disabled: boolean
  onEdit: (patch: Partial<DraftAdGroup>) => void
}) {
  const showCpc = acceptsCpc || adGroup.cpcBid.trim() !== ""
  const showCpa = acceptsCpa || adGroup.targetCpa.trim() !== ""
  const showRoas = acceptsRoas || adGroup.targetRoas.trim() !== ""
  const keywordBids = adGroup.keywords.some((keyword) => keyword.cpcBid.trim() !== "")
  return (
    <div className="grid gap-3">
      <div className="grid gap-3 sm:grid-cols-3">
        {showCpc ? (
          <MoneyField
            currency={currency}
            disabled={disabled}
            label="Default Click Bid"
            onChange={(cpcBid) => {
              onEdit({ cpcBid })
            }}
            value={adGroup.cpcBid}
          />
        ) : null}
        {showCpa ? (
          <MoneyField
            currency={currency}
            disabled={disabled}
            label="Target CPA"
            onChange={(targetCpa) => {
              onEdit({ targetCpa })
            }}
            value={adGroup.targetCpa}
          />
        ) : null}
        {showRoas ? (
          <RoasField
            disabled={disabled}
            onCommit={(targetRoas) => {
              onEdit({ targetRoas })
            }}
            value={adGroup.targetRoas}
          />
        ) : null}
      </div>
      {!showCpc && !showCpa && !showRoas ? (
        <p className="text-muted-foreground text-sm">
          This campaign's bidding has no settings to override per ad group.
        </p>
      ) : null}
      {keywordBids && !acceptsCpc ? (
        <Button
          className="w-fit"
          disabled={disabled}
          onClick={() => {
            onEdit({
              keywords: adGroup.keywords.map((keyword) => ({ ...keyword, cpcBid: "" })),
            })
          }}
          size="sm"
          type="button"
          variant="outline"
        >
          Remove Keyword Click Bids
        </Button>
      ) : null}
    </div>
  )
}

/** A percentage, edited on leaving the field, because the request holds it as a ratio. */
function RoasField({
  disabled,
  onCommit,
  value,
}: {
  disabled: boolean
  onCommit: (value: string) => void
  value: string
}) {
  const id = useId()
  return (
    <div className="grid min-w-0 gap-1">
      <label className="text-sm font-medium" htmlFor={id}>
        Target ROAS (%)
      </label>
      <Input
        key={value}
        className="text-sm tabular-nums"
        defaultValue={value}
        disabled={disabled}
        id={id}
        inputMode="decimal"
        onBlur={(event) => {
          if (event.currentTarget.value !== value) onCommit(event.currentTarget.value)
        }}
      />
    </div>
  )
}

const REVIEW_COLUMNS: DataColumn[] = [
  { key: "text", kind: "text", label: "Keyword", width: 240 },
  { key: "match", kind: "text", label: "Match Type", width: 120 },
  { key: "bid", kind: "text", label: "Click Bid", width: 100 },
  { key: "url", kind: "text", label: "Final URL", width: 200 },
  { key: "cancel", kind: "text", label: "Cancel", width: 70 },
]

/** The pasted keywords as a table, for match types, bids, and URLs. */
function KeywordReview({
  acceptsBids,
  disabled,
  keywords,
  onChange,
}: {
  acceptsBids: boolean
  disabled: boolean
  keywords: readonly DraftKeyword[]
  onChange: (keywords: DraftKeyword[]) => void
}) {
  const [open, setOpen] = useState(false)
  const rows = useMemo<DataRow[]>(
    () =>
      keywords.map((keyword, index) => ({
        bid: keyword.cpcBid,
        cancel: "",
        key: String(index),
        match: keyword.matchType,
        text: keyword.text,
        url: keyword.finalUrl,
      })),
    [keywords]
  )
  // Final URLs are rare, so the column stays in the column chooser until a keyword has one.
  const hasUrl = keywords.some((keyword) => keyword.finalUrl.trim() !== "")
  const columns = useMemo(
    () =>
      REVIEW_COLUMNS.filter((column) => acceptsBids || column.key !== "bid").map((column) =>
        column.key === "url" ? { ...column, hidden: !hasUrl } : column
      ),
    [acceptsBids, hasUrl]
  )
  if (keywords.length === 0) return null
  const update = (index: number, patch: Partial<DraftKeyword>) => {
    onChange(keywords.map((keyword, at) => (at === index ? { ...keyword, ...patch } : keyword)))
  }
  if (!open) {
    return (
      <Button
        className="w-fit"
        onClick={() => {
          setOpen(true)
        }}
        size="sm"
        type="button"
        variant="outline"
      >
        Review {approvalCountLine(keywords.length, "Keyword")}
      </Button>
    )
  }
  return (
    <DataTable
      columns={columns}
      exportFilename="google-ads-new-keywords.csv"
      pageSize={25}
      renderCell={(column, row) => {
        const index = Number(row["key"])
        const keyword = keywords[index]
        if (!keyword) return null
        if (column.key === "match")
          return (
            <MatchTypeCell
              disabled={disabled}
              keyword={keyword}
              onChange={(matchType) => {
                update(index, { matchType })
              }}
            />
          )
        if (column.key === "bid")
          return (
            <CommittedInput
              ariaLabel={`Click bid for ${keyword.text}`}
              disabled={disabled}
              onCommit={(cpcBid) => {
                update(index, { cpcBid: cpcBid.trim() })
              }}
              placeholder="Default"
              value={keyword.cpcBid}
            />
          )
        if (column.key === "url")
          return (
            <CommittedInput
              ariaLabel={`Final URL for ${keyword.text}`}
              disabled={disabled}
              onCommit={(finalUrl) => {
                update(index, { finalUrl: finalUrl.trim() })
              }}
              placeholder="Ad's URL"
              value={keyword.finalUrl}
            />
          )
        if (column.key === "cancel")
          return (
            <Button
              aria-label={`Cancel ${keyword.text}`}
              disabled={disabled}
              onClick={() => {
                onChange(keywords.filter((_, at) => at !== index))
              }}
              size="icon-xs"
              title="Cancel This Change"
              type="button"
              variant="ghost"
            >
              <XIcon />
            </Button>
          )
        return null
      }}
      rowDetails={false}
      rowNoun={["keyword", "keywords"]}
      rows={rows}
      searchable={keywords.length >= SEARCH_FROM}
    />
  )
}

function MatchTypeCell({
  disabled,
  keyword,
  onChange,
}: {
  disabled: boolean
  keyword: DraftKeyword
  onChange: (matchType: KeywordMatchType) => void
}) {
  return (
    <Select<KeywordMatchType>
      disabled={disabled}
      onValueChange={(next) => {
        if (next !== null) onChange(next)
      }}
      value={keyword.matchType}
    >
      <SelectTrigger aria-label={`Match type for ${keyword.text}`} size="sm">
        <SelectValue />
      </SelectTrigger>
      <SelectContent align="start">
        <SelectGroup>
          {MATCH_TYPES.map((option) => (
            <SelectItem key={option.value} label={option.label} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  )
}

/** The ad group's ads, one open at a time. */
function AdsEditor({
  ads,
  disabled,
  onChange,
}: {
  ads: DraftAdGroup["ads"]
  disabled: boolean
  onChange: (ads: DraftAdGroup["ads"]) => void
}) {
  const [open, setOpen] = useState(0)
  const at = Math.min(open, Math.max(ads.length - 1, 0))
  const ad = ads[at]
  return (
    <div className="grid min-w-0 gap-3">
      <div className="flex flex-wrap items-center gap-2">
        {ads.length > 1 ? (
          <SegmentedChoice
            ariaLabel="Ad"
            compact
            disabled={false}
            onChange={(value) => {
              setOpen(Number(value))
            }}
            options={ads.map((_, index) => ({
              value: String(index),
              label: `Ad ${String(index + 1)}`,
            }))}
            value={String(at)}
          />
        ) : null}
        {ads.length < MAX_ADS ? (
          <Button
            disabled={disabled}
            onClick={() => {
              onChange([...ads, blankAd(ads[0])])
              setOpen(ads.length)
            }}
            size="sm"
            type="button"
            variant="ghost"
          >
            <PlusIcon />
            Add Ad
          </Button>
        ) : null}
        {ad ? (
          <Button
            disabled={disabled}
            onClick={() => {
              onChange(ads.filter((_, index) => index !== at))
              setOpen(0)
            }}
            size="sm"
            type="button"
            variant="ghost"
          >
            <XIcon />
            Cancel This Change
          </Button>
        ) : null}
      </div>
      {ad ? (
        <AdCopyEditor
          key={at}
          ad={ad}
          disabled={disabled}
          onEdit={(patch) => {
            onChange(ads.map((item, index) => (index === at ? { ...item, ...patch } : item)))
          }}
        />
      ) : null}
    </div>
  )
}
