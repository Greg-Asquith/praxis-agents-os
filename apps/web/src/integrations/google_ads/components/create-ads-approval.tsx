// apps/web/src/integrations/google_ads/components/create-ads-approval.tsx

import { ChevronLeftIcon, ChevronRightIcon, XIcon } from "lucide-react"
import { useMemo, useState } from "react"

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { Button } from "@/components/ui/button"
import {
  DataTable,
  type DataColumn,
  type DataRow,
  type DataTableTab,
} from "@/components/ui/data-table"
import { Input } from "@/components/ui/input"
import { AttentionLine } from "@/integrations/ads/components/attention-line"
import { ChangeSummary, type ChangeSummaryLine } from "@/integrations/ads/components/change-summary"
import { Chip, TextField } from "@/integrations/ads/components/controls"
import { EntityPicker } from "@/integrations/ads/components/entity-picker"
import { StatusChoice } from "@/integrations/ads/components/status-choice"
import { SearchAdPreview } from "@/integrations/google_ads/components/search-ad-preview"
import { TextAssetList } from "@/integrations/google_ads/components/text-asset-list"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import {
  adGroupName,
  adRows,
  createAdsCounts,
  DESCRIPTION_LIMITS,
  DESCRIPTION_PINS,
  HEADLINE_LIMITS,
  HEADLINE_PINS,
  parseAdGroup,
  serializeAds,
  sharedValue,
  type AdRow,
  type CreateAdsArgs,
  type DraftAd,
} from "@/integrations/google_ads/lib/create-ads"

// Below this many ads the table's search only adds noise.
const SEARCH_FROM = 10

const COLUMNS: DataColumn[] = [
  { key: "adGroups", kind: "text", label: "Ad Group", width: 220 },
  { key: "headline", kind: "text", label: "Headline 1", width: 280 },
  { key: "headlines", kind: "number", label: "Headlines", width: 100 },
  { key: "descriptions", kind: "number", label: "Descriptions", width: 110 },
  { key: "cancel", kind: "text", label: "Cancel", width: 80 },
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

export function CreateAdsApproval({
  args,
  disabled,
  onFieldEdit,
}: {
  args: CreateAdsArgs
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
}) {
  const rows = useMemo(() => adRows(args), [args])
  const counts = createAdsCounts(rows)
  const [tab, setTab] = useState("all")
  const [open, setOpen] = useState(() => firstToOpen(rows))
  // Cancelled ads as sent, so Restore puts them back with their edits.
  const [cancelled, setCancelled] = useState<Record<string, unknown>[]>([])
  const openRow = rows[Math.min(open, rows.length - 1)]

  const editAds = (ads: DraftAd[]) => {
    onFieldEdit("ads", serializeAds(ads))
  }
  const editAd = (index: number, patch: Partial<DraftAd>) => {
    editAds(args.ads.map((ad, at) => (at === index ? { ...ad, ...patch } : ad)))
  }
  const editEvery = (patch: Partial<DraftAd>) => {
    editAds(args.ads.map((ad) => ({ ...ad, ...patch })))
  }
  const cancel = (indexes: ReadonlySet<number>) => {
    setCancelled([...cancelled, ...serializeAds(args.ads.filter((_, at) => indexes.has(at)))])
    editAds(args.ads.filter((_, at) => !indexes.has(at)))
    setOpen(0)
  }
  const restore = () => {
    onFieldEdit("ads", [...serializeAds(args.ads), ...cancelled])
    setCancelled([])
  }

  const many = rows.length > 1
  const tableRows = useMemo<DataRow[]>(
    () =>
      rows.map((row) => ({
        adGroups: adGroupsLine(row.ad, args),
        attention: row.problems.length > 0 ? "yes" : "no",
        cancel: "",
        descriptions: row.ad.descriptions.length,
        headline: row.ad.headlines[0]?.text ?? "",
        headlines: row.ad.headlines.length,
        key: String(row.index),
      })),
    [args, rows]
  )

  return (
    <div className="grid min-w-0 gap-3">
      <StatusChoice
        activeNote="Active, pending approval. Will go live once approved by Google."
        disabled={disabled}
        onChange={(status) => {
          onFieldEdit("status", status === "active" ? "ENABLED" : "PAUSED")
        }}
        pausedNote="Paused. Will not appear or spend until activated."
        value={args.status === "ENABLED" ? "active" : "paused"}
      />
      {many ? (
        <SharedSettings
          ads={args.ads}
          cancelled={cancelled.length}
          disabled={disabled}
          onCancelProblems={() => {
            cancel(new Set(rows.filter((row) => row.problems.length > 0).map((row) => row.index)))
          }}
          onEditEvery={editEvery}
          onRestore={restore}
          problems={counts.problems}
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
          exportFilename="google-ads-new-ads.csv"
          onTabChange={setTab}
          pageSize={25}
          renderCell={(column, row) => {
            const adRow = rows[Number(row["key"])]
            if (!adRow) return null
            if (column.key === "headline") return <HeadlineCell row={adRow} />
            if (column.key === "cancel")
              return (
                <Button
                  aria-label={`Cancel ad ${String(adRow.index + 1)}`}
                  disabled={disabled}
                  onClick={(event) => {
                    // The row opens the ad on click; cancelling shouldn't.
                    event.stopPropagation()
                    cancel(new Set([adRow.index]))
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
          onRowClick={(row) => {
            setOpen(Number(row["key"]))
          }}
          rowNoun={["ad", "ads"]}
          rows={tableRows}
          searchable={rows.length >= SEARCH_FROM}
          tabs={TABS}
        />
      ) : null}
      {!many && cancelled.length > 0 ? (
        <Button onClick={restore} size="sm" type="button" variant="outline">
          Restore {approvalCountLine(cancelled.length, "Cancelled Ad")}
        </Button>
      ) : null}
      {openRow ? (
        <AdEditor
          key={openRow.index}
          args={args}
          disabled={disabled}
          onEdit={(patch) => {
            editAd(openRow.index, patch)
          }}
          row={openRow}
          position={many ? { total: rows.length, onOpen: setOpen } : null}
        />
      ) : null}
    </div>
  )
}

function firstToOpen(rows: readonly AdRow[]): number {
  return rows.find((row) => row.problems.length > 0)?.index ?? 0
}

function adGroupsLine(ad: DraftAd, args: CreateAdsArgs): string {
  const [first, ...rest] = ad.adGroups
  if (first === undefined) return "No ad group"
  const name = adGroupName(first, args.checks)
  return rest.length ? `${name} +${String(rest.length)}` : name
}

function HeadlineCell({ row }: { row: AdRow }) {
  return (
    <span className="grid min-w-0 gap-0.5 whitespace-normal">
      <span className="font-medium wrap-anywhere">
        {row.ad.headlines[0]?.text.trim()
          ? row.ad.headlines[0].text
          : `Ad ${String(row.index + 1)}`}
      </span>
      {row.problems[0] ? (
        <span className="text-destructive text-xs wrap-anywhere">{row.problems[0]}</span>
      ) : null}
    </span>
  )
}

/** Settings every ad shares, edited once, with the lines for problems and cancelled ads. */
function SharedSettings({
  ads,
  cancelled,
  disabled,
  onCancelProblems,
  onEditEvery,
  onRestore,
  problems,
}: {
  ads: readonly DraftAd[]
  cancelled: number
  disabled: boolean
  onCancelProblems: () => void
  onEditEvery: (patch: Partial<DraftAd>) => void
  onRestore: () => void
  problems: number
}) {
  const finalUrl = sharedValue(ads, "finalUrl")
  const path1 = sharedValue(ads, "path1")
  const path2 = sharedValue(ads, "path2")
  const lines: ChangeSummaryLine[] = [
    {
      id: "final_url",
      label: "Final URL for every ad",
      count: finalUrl === null ? 0 : ads.length,
      action: (
        <Input
          aria-label="Final URL for every ad"
          className="w-80 max-w-full text-sm"
          disabled={disabled}
          onChange={(event) => {
            onEditEvery({ finalUrl: event.currentTarget.value })
          }}
          value={finalUrl ?? ""}
        />
      ),
    },
    {
      id: "paths",
      label: "Display paths for every ad",
      count: path1 === null || path2 === null ? 0 : ads.length,
      action: (
        <span className="flex gap-2">
          <Input
            aria-label="Path 1 for every ad"
            className="w-32 text-sm"
            disabled={disabled}
            onChange={(event) => {
              onEditEvery({ path1: event.currentTarget.value })
            }}
            value={path1 ?? ""}
          />
          <Input
            aria-label="Path 2 for every ad"
            className="w-28 text-sm"
            disabled={disabled}
            onChange={(event) => {
              onEditEvery({ path2: event.currentTarget.value })
            }}
            value={path2 ?? ""}
          />
        </span>
      ),
    },
    {
      id: "attention",
      label: "Needs Attention",
      count: problems,
      tone: "danger",
      action: (
        <Button
          disabled={disabled}
          onClick={onCancelProblems}
          size="sm"
          type="button"
          variant="outline"
        >
          Cancel These {String(problems)}
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
  return <ChangeSummary lines={lines} />
}

function AdEditor({
  args,
  disabled,
  onEdit,
  position,
  row,
}: {
  args: CreateAdsArgs
  disabled: boolean
  onEdit: (patch: Partial<DraftAd>) => void
  // Set when the card has more than one ad, to say which this is and step between them.
  position: { total: number; onOpen: (index: number) => void } | null
  row: AdRow
}) {
  const { ad } = row
  const chosen = new Set(ad.adGroups.map((group) => group.key))
  return (
    <section
      aria-label={position ? `Ad ${String(row.index + 1)}` : "Ad"}
      className="grid min-w-0 gap-4 rounded-lg border px-3 py-3"
    >
      {position ? (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm font-medium">
            Ad {String(row.index + 1)} of {String(position.total)}
            <span className="text-muted-foreground font-normal">
              {" "}
              · {approvalCountLine(ad.headlines.length, "headline")} ·{" "}
              {approvalCountLine(ad.descriptions.length, "description")}
            </span>
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
      <SearchAdPreview ad={ad} />
      <TextAssetList
        assets={ad.headlines}
        disabled={disabled}
        limits={HEADLINE_LIMITS}
        noun="Headline"
        onChange={(headlines) => {
          onEdit({ headlines })
        }}
        pins={HEADLINE_PINS}
      />
      <TextAssetList
        assets={ad.descriptions}
        disabled={disabled}
        limits={DESCRIPTION_LIMITS}
        noun="Description"
        onChange={(descriptions) => {
          onEdit({ descriptions })
        }}
        pins={DESCRIPTION_PINS}
      />
      <div className="grid gap-3 sm:grid-cols-2">
        <TextField
          disabled={disabled}
          label="Final URL"
          onChange={(finalUrl) => {
            onEdit({ finalUrl })
          }}
          value={ad.finalUrl}
        />
        <TextField
          disabled={disabled}
          label="Mobile URL (Optional)"
          onChange={(mobileFinalUrl) => {
            onEdit({ mobileFinalUrl })
          }}
          value={ad.mobileFinalUrl}
        />
        <TextField
          disabled={disabled}
          label="Path 1"
          onChange={(path1) => {
            onEdit({ path1 })
          }}
          value={ad.path1}
        />
        <TextField
          disabled={disabled}
          label="Path 2"
          onChange={(path2) => {
            onEdit({ path2 })
          }}
          value={ad.path2}
        />
      </div>
      <div className="grid gap-2">
        <p className="text-sm font-medium">Ad Groups</p>
        <div className="flex flex-wrap gap-1.5">
          {ad.adGroups.map((group) => (
            <Chip
              key={group.key}
              disabled={disabled}
              label={adGroupName(group, args.checks)}
              onRemove={() => {
                onEdit({ adGroups: ad.adGroups.filter((item) => item.key !== group.key) })
              }}
            />
          ))}
        </div>
        {ad.adGroups.length < 10 ? (
          <EntityPicker
            currentLabel={null}
            disabled={disabled}
            entityKind="google_ads_ad_group"
            fieldKey="ads"
            label="Add an Ad Group"
            onChoose={(reference) => {
              const target = parseAdGroup(reference)
              if (target && !chosen.has(target.key)) onEdit({ adGroups: [...ad.adGroups, target] })
            }}
            toolName="google_ads_create_ads"
          />
        ) : null}
      </div>
    </section>
  )
}
