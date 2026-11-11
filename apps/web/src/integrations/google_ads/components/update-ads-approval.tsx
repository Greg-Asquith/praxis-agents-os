// apps/web/src/integrations/google_ads/components/update-ads-approval.tsx

import { XIcon } from "lucide-react"
import { useMemo, useState } from "react"

import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-types"
import type { EditedValue } from "@/components/tool-ui/edited-values"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DataTable,
  type DataColumn,
  type DataRow,
  type DataTableTab,
} from "@/components/ui/data-table"
import { Input } from "@/components/ui/input"
import { AttentionLine } from "@/integrations/ads/components/attention-line"
import { ChangeBanner } from "@/integrations/ads/components/change-banner"
import { ChangeSummary } from "@/integrations/ads/components/change-summary"
import { FormField, TextField } from "@/integrations/ads/components/controls"
import { ParentTable, type ParentRow } from "@/integrations/ads/components/parent-table"
import { CheckChanges } from "@/integrations/google_ads/components/check-changes"
import { SearchAdPreview } from "@/integrations/google_ads/components/search-ad-preview"
import { TextAssetList } from "@/integrations/google_ads/components/text-asset-list"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import {
  characterCount,
  DESCRIPTION_LIMITS,
  DESCRIPTION_PINS,
  HEADLINE_LIMITS,
  HEADLINE_PINS,
  type TextAsset,
} from "@/integrations/google_ads/lib/create-ads"
import {
  adCounts,
  adGroupOf,
  adRows,
  adsNeedCheck,
  cancelledEntries,
  canCheckAds,
  editsFor,
  editsLine,
  previewCopy,
  restoredAds,
  sharedEdits,
  updateAdsBannerDetail,
  withEdits,
  type AdEdits,
  type AdRow,
  type LiveCopy,
  type UpdateAdsArgs,
} from "@/integrations/google_ads/lib/update-ads"
import { cn } from "@/lib/utils"

// Below this many ads the summary and the table tools only add noise.
const TOOLS_FROM = 10

const COLUMNS: DataColumn[] = [
  { key: "ad", kind: "text", label: "Ad", width: 320 },
  // The ad groups table above names them, so these columns are for the chooser and the export.
  { key: "adGroup", kind: "text", label: "Ad Group", width: 170, hidden: true },
  { key: "campaign", kind: "text", label: "Campaign", width: 170, hidden: true },
  { key: "headlines", kind: "text", label: "Headlines", width: 100 },
  { key: "cancel", kind: "text", label: "Cancel", width: 80 },
]

const PARENT_COLUMNS: DataColumn[] = [
  { key: "ads", kind: "number", label: "Ads", width: 90 },
  { key: "problems", kind: "text", label: "Problems", width: 140 },
]

export function UpdateAdsApproval({
  args,
  checked,
  controls,
  disabled,
  onFieldEdit,
}: {
  args: UpdateAdsArgs
  // The request Google last answered for.
  checked: UpdateAdsArgs
  controls: ToolApprovalDecisionControls
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
}) {
  const cancelled = useMemo(
    () => cancelledEntries(controls.retained, args),
    [args, controls.retained]
  )
  const rows = useMemo(() => adRows(args, checked, cancelled), [args, checked, cancelled])
  const byKey = useMemo(() => new Map(rows.map((row) => [row.key, row])), [rows])
  const counts = adCounts(rows)
  const shared = sharedEdits(args)
  const [tab, setTab] = useState("all")
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set())
  // A shared edit is changed once for every ad, so no ad opens until the operator picks one.
  const [open, setOpen] = useState<string | null>(() =>
    shared ? null : ((rows.find((row) => row.problems.length > 0) ?? rows[0])?.key ?? null)
  )
  const many = rows.length > 1
  const tools = rows.length >= TOOLS_FROM
  const openRow = many ? (open ? byKey.get(open) : undefined) : rows[0]
  const [adGroup, setAdGroup] = useState<string | null>(null)
  const parents = useMemo(() => adGroupParents(rows), [rows])
  const shown = adGroup === null ? rows : rows.filter((row) => adGroupOf(row.change) === adGroup)

  // A review redraws the card, so cancelled ads live beside the request for Undo.
  const save = (
    changes: Record<string, unknown>[],
    nextCancelled: readonly Record<string, unknown>[]
  ) => {
    if (nextCancelled !== cancelled) controls.onRetain?.(nextCancelled)
    onFieldEdit("changes", changes)
  }
  const editAd = (key: string, edits: AdEdits) => {
    save(
      args.changes.map((change) =>
        change.key === key ? withEdits(change.entry, edits) : change.entry
      ),
      cancelled
    )
  }
  const editEvery = (edits: AdEdits) => {
    save(
      args.changes.map((change) => withEdits(change.entry, edits)),
      cancelled
    )
  }
  const cancel = (keys: ReadonlySet<string>) => {
    save(
      args.changes.filter((change) => !keys.has(change.key)).map((change) => change.entry),
      [
        ...cancelled,
        ...args.changes.filter((change) => keys.has(change.key)).map((change) => change.entry),
      ]
    )
  }
  const undo = (match: (row: AdRow["change"]) => boolean) => {
    const restored = restoredAds(args, cancelled, match)
    save(restored.changes, restored.cancelled)
  }

  const sample = rows.find((row) => !row.cancelled && row.current && row.after)

  return (
    <div className="grid min-w-0 gap-3">
      <ChangeBanner
        aside={
          <p className="text-sm font-medium tabular-nums">
            {approvalCountLine(counts.apply, "ad")}
          </p>
        }
        detail={updateAdsBannerDetail(counts)}
        title="Edited ads go back through Google's review"
      />
      {many && shared && sample ? (
        <SharedChange disabled={disabled} edits={shared} onEdit={editEvery} sample={sample} />
      ) : null}
      {tools ? (
        <ChangeSummary
          lines={[
            {
              id: "edit",
              label: shared ? editsLine(shared) : "Edit ads",
              count: counts.ads - counts.problems,
              onSelect: () => {
                setTab("all")
              },
              selected: tab === "all",
            },
            {
              action: (
                <Button
                  disabled={disabled}
                  onClick={() => {
                    cancel(
                      new Set(
                        rows
                          .filter((row) => !row.cancelled && row.problems.length > 0)
                          .map((row) => row.key)
                      )
                    )
                  }}
                  size="sm"
                  type="button"
                  variant="outline"
                >
                  Cancel These {String(counts.problems)}
                </Button>
              ),
              count: counts.problems,
              id: "attention",
              label: "Needs Attention",
              onSelect: () => {
                setTab("attention")
              },
              selected: tab === "attention",
              tone: "danger",
            },
          ]}
        />
      ) : null}
      {many ? (
        <>
          <AttentionLine
            count={counts.problems}
            onShow={() => {
              setAdGroup(null)
              setTab("attention")
            }}
          />
          <ParentTable
            columns={PARENT_COLUMNS}
            disabled={disabled}
            label="Ad Groups"
            onCancel={(key) => {
              cancel(
                new Set(
                  rows
                    .filter((row) => !row.cancelled && adGroupOf(row.change) === key)
                    .map((row) => row.key)
                )
              )
            }}
            onSelect={(key) => {
              setAdGroup(key)
              // A shared edit stays closed; otherwise open the ad group's first ad to fix.
              if (shared || key === null) return
              const inGroup = rows.filter((row) => !row.cancelled && adGroupOf(row.change) === key)
              setOpen((inGroup.find((row) => row.problems.length > 0) ?? inGroup[0])?.key ?? null)
            }}
            onUndo={(key) => {
              undo((change) => adGroupOf(change) === key)
            }}
            rowNoun={["ad group", "ad groups"]}
            rows={parents}
            selected={adGroup}
          />
          <DataTable
            activeTab={tab}
            columns={COLUMNS}
            exportFilename="google-ads-ad-changes.csv"
            onRowClick={(dataRow) => {
              setOpen(String(dataRow["id"]))
            }}
            onTabChange={setTab}
            pageSize={25}
            renderCell={(column, dataRow) => {
              const row = byKey.get(String(dataRow["id"]))
              if (!row) return null
              if (column.key === "ad") return <AdCell row={row} />
              if (column.key === "cancel")
                return (
                  <CancelCell
                    disabled={disabled}
                    onCancel={() => {
                      cancel(new Set([row.key]))
                    }}
                    onUndo={() => {
                      undo((change) => change.key === row.key)
                    }}
                    row={row}
                  />
                )
              return null
            }}
            rowClassName={(dataRow) => {
              const row = byKey.get(String(dataRow["id"]))
              if (row?.cancelled) return "opacity-60"
              return row?.key === openRow?.key
                ? "bg-muted/70 shadow-[inset_3px_0_0_var(--primary)]"
                : undefined
            }}
            rowDetails={false}
            rowNoun={["ad", "ads"]}
            rows={shown.map((row) => ({
              ad: row.name,
              adGroup: row.adGroupName,
              campaign: row.campaignName,
              cancel: "",
              headlines: `${String(row.current?.headlines.length ?? "—")} → ${String(row.after?.headlines.length ?? "—")}`,
              id: row.key,
            }))}
            {...(tools
              ? {
                  searchable: true,
                  selection: {
                    actions: (
                      <Button
                        disabled={disabled}
                        onClick={() => {
                          cancel(selected)
                          setSelected(new Set())
                        }}
                        size="sm"
                        type="button"
                        variant="outline"
                      >
                        Cancel These Changes
                      </Button>
                    ),
                    onChange: setSelected,
                    rowId: (dataRow: DataRow) => String(dataRow["id"]),
                    selected,
                  },
                }
              : {})}
            tabs={tabs(byKey)}
          />
        </>
      ) : null}
      {openRow && !openRow.cancelled ? (
        <AdEditor
          key={openRow.key}
          disabled={disabled}
          onEdit={(edits) => {
            editAd(openRow.key, edits)
          }}
          row={openRow}
          titled={many}
        />
      ) : null}
      {adsNeedCheck(args, checked) && args.changes.length > 0 ? (
        <CheckChanges
          canCheck={canCheckAds(args, checked)}
          disabled={disabled}
          label={
            [...checked.checks.values()].some((check) => check.unavailable)
              ? "Check Again"
              : "Check Changes"
          }
          note="You changed this request, so Google needs to check it again."
          onCheck={controls.onReview}
          submitting={controls.submitting}
        />
      ) : null}
    </div>
  )
}

function tabs(byKey: ReadonlyMap<string, AdRow>): DataTableTab[] {
  return [
    { id: "all", label: "All", match: () => true },
    {
      hideWhenEmpty: true,
      id: "attention",
      label: "Needs Attention",
      match: (dataRow) => {
        const row = byKey.get(String(dataRow["id"]))
        return row !== undefined && !row.cancelled && row.problems.length > 0
      },
    },
  ]
}

/** One row per ad group the ads are in, in the order its ads first appear. */
function adGroupParents(rows: readonly AdRow[]): ParentRow[] {
  const groups = new Map<string, AdRow[]>()
  for (const row of rows) {
    const key = adGroupOf(row.change)
    groups.set(key, [...(groups.get(key) ?? []), row])
  }
  return [...groups].map(([key, items]) => {
    const live = items.filter((row) => !row.cancelled)
    const named = items.find((row) => row.adGroupName)
    const problems = live.filter((row) => row.problems.length > 0).length
    return {
      cancelled: live.length === 0,
      context: named?.campaignName ?? null,
      key,
      name: named ? named.adGroupName : `Ad group ${items[0]?.change.adGroupId ?? ""}`,
      problems,
      values: {
        ads: live.length,
        problems:
          live.length === 0 ? "Cancelled" : problems > 0 ? `${String(problems)} to fix` : "None",
      },
    }
  })
}

function AdCell({ row }: { row: AdRow }) {
  return (
    <div className="grid min-w-0 gap-0.5 text-sm">
      <span className="font-medium wrap-anywhere whitespace-normal">
        {row.name}
        {row.unchanged && !row.cancelled ? (
          <Badge className="ml-2" variant="secondary">
            Already Set
          </Badge>
        ) : null}
      </span>
      {!row.cancelled && row.problems[0] ? (
        <span className="text-destructive text-xs wrap-anywhere whitespace-normal">
          {row.problems[0]}
        </span>
      ) : null}
    </div>
  )
}

function CancelCell({
  disabled,
  onCancel,
  onUndo,
  row,
}: {
  disabled: boolean
  onCancel: () => void
  onUndo: () => void
  row: AdRow
}) {
  // The row opens its ad on click; these buttons shouldn't.
  return row.cancelled ? (
    <Button
      disabled={disabled}
      onClick={(event) => {
        event.stopPropagation()
        onUndo()
      }}
      size="sm"
      type="button"
      variant="ghost"
    >
      Undo
    </Button>
  ) : (
    <Button
      aria-label="Cancel This Change"
      disabled={disabled}
      onClick={(event) => {
        event.stopPropagation()
        onCancel()
      }}
      size="icon-xs"
      title="Cancel This Change"
      type="button"
      variant="ghost"
    >
      <XIcon />
    </Button>
  )
}

/** The ad now and after the edit, as search results side by side. */
function NowAndAfter({ after, current }: { after: LiveCopy; current: LiveCopy }) {
  return (
    <div className="grid min-w-0 gap-3 sm:grid-cols-2">
      {(
        [
          ["Now", current],
          ["After", after],
        ] as const
      ).map(([label, copy]) => (
        <div key={label} className="grid min-w-0 content-start gap-1.5">
          <p className="text-muted-foreground text-xs font-medium uppercase">{label}</p>
          <SearchAdPreview ad={previewCopy(copy)} />
        </div>
      ))}
    </div>
  )
}

/** One edit shared by every ad, changed once: each replaced headline or description, then a preview. */
function SharedChange({
  disabled,
  edits,
  onEdit,
  sample,
}: {
  disabled: boolean
  edits: AdEdits
  onEdit: (edits: AdEdits) => void
  sample: AdRow
}) {
  const pairs = (removed: readonly string[] = [], added: readonly TextAsset[] = []) =>
    removed
      .slice(0, added.length)
      .map((from, index) => ({ from, index, to: added[index]?.text ?? "" }))
  const replace = (
    kind: "headline" | "description",
    index: number,
    side: "from" | "to",
    value: string
  ) => {
    const removeKey = kind === "headline" ? "remove_headlines" : "remove_descriptions"
    const addKey = kind === "headline" ? "add_headlines" : "add_descriptions"
    if (side === "from")
      onEdit({
        ...edits,
        [removeKey]: (edits[removeKey] ?? []).map((item, at) => (at === index ? value : item)),
      })
    else
      onEdit({
        ...edits,
        [addKey]: (edits[addKey] ?? []).map((item, at) =>
          at === index ? { ...item, text: value } : item
        ),
      })
  }
  const lines = [
    ...pairs(edits.remove_headlines, edits.add_headlines).map((pair) => ({
      ...pair,
      kind: "headline" as const,
    })),
    ...pairs(edits.remove_descriptions, edits.add_descriptions).map((pair) => ({
      ...pair,
      kind: "description" as const,
    })),
  ]
  return (
    <section aria-label="The change" className="grid min-w-0 gap-3 rounded-lg border px-3 py-3">
      <p className="text-sm font-medium">{editsLine(edits)}</p>
      {lines.map((line) => {
        const limit = line.kind === "headline" ? HEADLINE_LIMITS.length : DESCRIPTION_LIMITS.length
        const count = characterCount(line.to.trim())
        const noun = line.kind === "headline" ? "Headline" : "Description"
        return (
          <div key={`${line.kind}-${String(line.index)}`} className="grid gap-2 sm:grid-cols-2">
            <FormField label={`Replace ${noun}`}>
              {(id) => (
                <Input
                  className="text-sm"
                  id={id}
                  disabled={disabled}
                  onChange={(event) => {
                    replace(line.kind, line.index, "from", event.currentTarget.value)
                  }}
                  value={line.from}
                />
              )}
            </FormField>
            <FormField label="With">
              {(id) => (
                <span className="flex items-center gap-2">
                  <Input
                    aria-invalid={count === 0 || count > limit}
                    id={id}
                    className="text-sm"
                    disabled={disabled}
                    onChange={(event) => {
                      replace(line.kind, line.index, "to", event.currentTarget.value)
                    }}
                    value={line.to}
                  />
                  <span
                    className={cn(
                      "w-12 shrink-0 text-right text-xs tabular-nums",
                      count > limit ? "text-destructive font-medium" : "text-muted-foreground"
                    )}
                  >
                    {String(count)}/{String(limit)}
                  </span>
                </span>
              )}
            </FormField>
          </div>
        )
      })}
      {sample.current && sample.after ? (
        <NowAndAfter after={sample.after} current={sample.current} />
      ) : null}
    </section>
  )
}

/** One ad's copy after the edit, editable, with the ad now and after above it. */
function AdEditor({
  disabled,
  onEdit,
  row,
  titled,
}: {
  disabled: boolean
  onEdit: (edits: AdEdits) => void
  row: AdRow
  // Set when the card has more than one ad, to say which this is.
  titled: boolean
}) {
  const { after, current } = row
  const change = (patch: Partial<LiveCopy>) => {
    if (current && after) onEdit(editsFor(current, { ...after, ...patch }))
  }
  return (
    <section
      aria-label={titled ? row.name : "Ad"}
      className="grid min-w-0 gap-4 rounded-lg border px-3 py-3"
    >
      {titled ? (
        <p className="text-sm font-medium">
          {row.name}
          {row.adGroupName ? (
            <span className="text-muted-foreground font-normal"> · {row.adGroupName}</span>
          ) : null}
        </p>
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
      {current && after ? (
        <>
          <NowAndAfter after={after} current={current} />
          <TextAssetList
            assets={after.headlines}
            disabled={disabled}
            limits={HEADLINE_LIMITS}
            noun="Headline"
            onChange={(headlines) => {
              change({ headlines })
            }}
            pins={HEADLINE_PINS}
          />
          <TextAssetList
            assets={after.descriptions}
            disabled={disabled}
            limits={DESCRIPTION_LIMITS}
            noun="Description"
            onChange={(descriptions) => {
              change({ descriptions })
            }}
            pins={DESCRIPTION_PINS}
          />
          <div className="grid gap-3 sm:grid-cols-3">
            <TextField
              disabled={disabled}
              label="Final URL"
              onChange={(finalUrl) => {
                change({ finalUrl })
              }}
              value={after.finalUrl ?? ""}
            />
            <TextField
              disabled={disabled}
              label="Path 1"
              onChange={(path1) => {
                change({ path1: path1 || null })
              }}
              value={after.path1 ?? ""}
            />
            <TextField
              disabled={disabled}
              label="Path 2"
              onChange={(path2) => {
                change({ path2: path2 || null })
              }}
              value={after.path2 ?? ""}
            />
          </div>
        </>
      ) : null}
    </section>
  )
}
