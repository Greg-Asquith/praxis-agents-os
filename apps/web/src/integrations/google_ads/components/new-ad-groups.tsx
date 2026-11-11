// apps/web/src/integrations/google_ads/components/new-ad-groups.tsx

import { ChevronLeftIcon, ChevronRightIcon, PlusIcon, XIcon } from "lucide-react"
import { useId, useMemo, useState } from "react"

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
import { ChangeSummary } from "@/integrations/ads/components/change-summary"
import { CommittedInput } from "@/integrations/ads/components/committed-input"
import { SegmentedChoice } from "@/integrations/ads/components/controls"
import { KeywordPaste } from "@/integrations/ads/components/keyword-paste"
import { MoneyField } from "@/integrations/ads/components/money-field"
import { SettingLine, SettingRow, SettingRows } from "@/integrations/ads/components/setting-rows"
import type { KeywordMatchType } from "@/integrations/ads/lib/keyword-notation"
import { AdCopyEditor } from "@/integrations/google_ads/components/ad-copy-editor"
import { NewAssetsEditor } from "@/integrations/google_ads/components/new-assets-editor"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import {
  blankAd,
  blankAdGroup,
  keywordMixLine,
  MAX_ADS,
  mergePastedKeywords,
  NEEDS_AD,
  NEEDS_KEYWORD,
  type AdGroupRow,
  type BidRules,
  type CreateAdGroupsCounts,
  type DraftAdGroup,
  type DraftKeyword,
} from "@/integrations/google_ads/lib/create-ad-groups"
import { assetSummary, isAssetProblem } from "@/integrations/google_ads/lib/new-assets"

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

/** New ad groups: a table when there's more than one, and the open one's settings below it. */
export function NewAdGroups({
  currency,
  disabled,
  onCancel,
  onSave,
  rows,
  rules,
}: {
  currency: string | null
  disabled: boolean
  // Takes the given ad groups, by position, out of the request.
  onCancel: (indexes: ReadonlySet<number>) => void
  onSave: (adGroups: DraftAdGroup[]) => void
  rows: readonly AdGroupRow[]
  // The campaign's bidding rules, or null while they aren't known.
  rules: BidRules | null
}) {
  const [tab, setTab] = useState("all")
  const [open, setOpen] = useState(() => firstToOpen(rows))
  const openRow = rows[Math.min(open, rows.length - 1)]
  const many = rows.length > 1
  const problems = rows.filter((row) => row.problems.length > 0).length

  const edit = (index: number, patch: Partial<DraftAdGroup>) => {
    onSave(rows.map((row) => (row.index === index ? { ...row.adGroup, ...patch } : row.adGroup)))
  }
  const cancel = (indexes: ReadonlySet<number>) => {
    onCancel(indexes)
    setOpen(0)
  }
  const adGroups = rows.map((row) => row.adGroup)
  const blank = blankAdGroup(adGroups)

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

  return (
    <>
      <AttentionLine
        count={problems}
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
          currency={currency}
          disabled={disabled}
          onEdit={(patch) => {
            edit(openRow.index, patch)
          }}
          position={many ? { total: rows.length, onOpen: setOpen } : null}
          row={openRow}
          rules={rules}
        />
      ) : null}
      {blank ? (
        <Button
          className="w-fit"
          disabled={disabled}
          onClick={() => {
            onSave([...adGroups, blank])
            setOpen(rows.length)
          }}
          size="sm"
          type="button"
          variant="outline"
        >
          <PlusIcon />
          Add Ad Group
        </Button>
      ) : null}
    </>
  )
}

/** Problems that stop the whole request, listed once above the ad groups. */
export function ProblemList({ problems }: { problems: readonly string[] }) {
  if (problems.length === 0) return null
  return (
    <ul className="text-destructive grid gap-0.5 text-sm" role="alert">
      {problems.map((problem) => (
        <li key={problem} className="wrap-anywhere">
          {problem}
        </li>
      ))}
    </ul>
  )
}

/** The change summary for new ad groups: counts, Cancel These N, and Restore. */
export function AdGroupSummary({
  cancelled,
  counts,
  detail,
  disabled,
  keywordMix,
  onCancelProblems,
  onRestore,
}: {
  cancelled: number
  counts: CreateAdGroupsCounts
  // Where the ad groups go, such as "in Trail".
  detail: string
  disabled: boolean
  keywordMix: string
  onCancelProblems: () => void
  onRestore: () => void
}) {
  return (
    <ChangeSummary
      lines={[
        { id: "ad_groups", label: "Ad Groups", detail, count: counts.adGroups },
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
            <Button
              disabled={disabled}
              onClick={onRestore}
              size="sm"
              type="button"
              variant="outline"
            >
              Restore
            </Button>
          ),
        },
      ]}
    />
  )
}

function firstToOpen(rows: readonly AdGroupRow[]): number {
  return rows.find((row) => row.problems.length > 0)?.index ?? 0
}

function AdGroupEditor({
  currency,
  disabled,
  onEdit,
  position,
  row,
  rules,
}: {
  currency: string | null
  disabled: boolean
  onEdit: (patch: Partial<DraftAdGroup>) => void
  // Set when the card has more than one ad group, to say which this is and step between them.
  position: { total: number; onOpen: (index: number) => void } | null
  row: AdGroupRow
  rules: BidRules | null
}) {
  const { adGroup } = row
  const nameId = useId()
  const check = rules
  const mix = keywordMixLine([row])
  const adProblems = row.problems.filter(
    (problem) => problem === NEEDS_AD || /^Ad \d/.test(problem)
  )
  const assetProblems = row.problems.filter(isAssetProblem)
  return (
    <section
      aria-label={adGroup.name || "Ad group"}
      className="min-w-0 divide-y overflow-hidden rounded-lg border"
    >
      {position || row.problems.length > 0 ? (
        <div className="grid gap-2 px-3 py-2">
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
          <ProblemList problems={row.problems} />
        </div>
      ) : null}
      <SettingRows ariaLabel={`${adGroup.name} settings`} bare defaultOpen="keywords">
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
          tone={row.problems.includes(NEEDS_KEYWORD) ? "error" : "neutral"}
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
        <SettingRow
          rowKey="assets"
          summary={assetSummary(adGroup.assets)}
          title="Sitelinks and Callouts"
          tone={assetProblems.length > 0 ? "error" : "neutral"}
        >
          <NewAssetsEditor
            assets={adGroup.assets}
            disabled={disabled}
            onChange={(assets) => {
              onEdit({ assets })
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

export function MatchTypeCell({
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
