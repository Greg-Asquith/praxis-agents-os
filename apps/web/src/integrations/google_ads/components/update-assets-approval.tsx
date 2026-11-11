// apps/web/src/integrations/google_ads/components/update-assets-approval.tsx

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
import { AttentionLine } from "@/integrations/ads/components/attention-line"
import { CancelCell } from "@/integrations/ads/components/cancel-cell"
import { ChangeBanner } from "@/integrations/ads/components/change-banner"
import { ChangeSummary, type ChangeSummaryLine } from "@/integrations/ads/components/change-summary"
import { EntityPicker } from "@/integrations/ads/components/entity-picker"
import { ParentTable } from "@/integrations/ads/components/parent-table"
import {
  parseCancelled,
  restoreParent,
  restoreRow,
  retainCancelled,
  serializeCancelled,
  type CancelledChanges,
} from "@/integrations/ads/lib/cancelled-rows"
import { CheckChanges } from "@/integrations/google_ads/components/check-changes"
import { ProblemList } from "@/integrations/google_ads/components/new-ad-groups"
import {
  AssetFieldInput,
  NewAssetTable,
} from "@/integrations/google_ads/components/new-assets-editor"
import {
  ASSET_FIELDS,
  ASSET_TYPE_LABELS,
  assetDatesText,
  type AssetType,
} from "@/integrations/google_ads/lib/new-assets"
import {
  addTarget,
  ASSET_CANCEL_CARD,
  assetCounts,
  assetLimitProblems,
  assetParents,
  cancelLinks,
  canCheckAssets,
  changeRows,
  checkIncomplete,
  editChange,
  editNewAsset,
  linkRows,
  needsCheck,
  newAssetRows,
  parseCancelledChanges,
  serializeArgs,
  type AssetChange,
  type AssetTarget,
  type ChangeRow,
  type LinkRow,
  type UpdateAssetsArgs,
} from "@/integrations/google_ads/lib/update-assets"
import { cn } from "@/lib/utils"

const TOOL = "google_ads_update_assets"
// Below this many changes the summary and the table tools only add noise.
const TOOLS_FROM = 10

const PARENT_COLUMNS: DataColumn[] = [
  { key: "sitelinks", kind: "number", label: "Sitelinks Now", width: 120 },
  { key: "callouts", kind: "number", label: "Callouts Now", width: 120 },
  { key: "add", kind: "number", label: "To Add", width: 90 },
  { key: "remove", kind: "number", label: "To Remove", width: 100 },
  { key: "problems", kind: "text", label: "Problems", width: 110 },
]

const LINK_COLUMNS: DataColumn[] = [
  { key: "asset", kind: "text", label: "Asset", width: 240 },
  { key: "type", kind: "text", label: "Type", width: 100 },
  { key: "change", kind: "text", label: "Change", width: 140 },
  { key: "target", kind: "text", label: "Where", width: 220 },
  { key: "cancel", kind: "text", label: "Cancel", width: 70 },
]

const NEW_ASSET_TITLES: Record<AssetType, string> = {
  CALLOUT: "New Callouts",
  SITELINK: "New Sitelinks",
}

const NOTHING_LEFT = { entries: [], rows: [] }

export function UpdateAssetsApproval({
  args,
  checked,
  controls,
  disabled,
  onFieldEdit,
}: {
  args: UpdateAssetsArgs
  // The request Google last answered for.
  checked: UpdateAssetsArgs
  controls: ToolApprovalDecisionControls
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
}) {
  const cancelled = useMemo(
    () => parseCancelled(ASSET_CANCEL_CARD, controls.retained),
    [controls.retained]
  )
  const cancelledChanges = useMemo(
    () => parseCancelledChanges(controls.retained),
    [controls.retained]
  )
  const rows = useMemo(
    () => linkRows(args, checked, cancelled.rows),
    [args, checked, cancelled.rows]
  )
  const changes = useMemo(
    () => changeRows(args, checked, cancelledChanges),
    [args, checked, cancelledChanges]
  )
  const counts = assetCounts(rows, changes)
  const [target, setTarget] = useState<string | null>(null)
  const [tab, setTab] = useState("all")
  const accountCount = new Set(rows.map((row) => row.targetKey.split("/")[1])).size
  const parents = useMemo(
    () => assetParents(args, rows, accountCount > 1),
    [accountCount, args, rows]
  )
  const newAssets = newAssetRows(rows, args)
  const shown = target === null ? rows : rows.filter((row) => row.targetKey === target)
  const live = rows.filter((row) => !row.cancelled)
  const blocked = live.filter((row) => row.problem !== null)

  // Cancelled links and content changes stay beside the request, so Undo can restore them.
  const retain = (links: CancelledChanges<AssetTarget, LinkRow>, edits: readonly AssetChange[]) => {
    controls.onRetain?.({
      ...serializeCancelled(ASSET_CANCEL_CARD, links),
      changes: edits.map((change) => change.value),
    })
  }
  const saveEntries = (
    next: AssetTarget[],
    left: { entries: readonly AssetTarget[]; rows: readonly LinkRow[] } = NOTHING_LEFT,
    held = cancelled
  ) => {
    const rowIds = new Set(linkRows({ ...args, entries: next }, checked).map((row) => row.id))
    retain(retainCancelled(held, left, { entries: next, rowIds }), cancelledChanges)
    onFieldEdit("entries", serializeArgs({ ...args, entries: next }).entries)
  }
  const saveChanges = (next: AssetChange[], held: readonly AssetChange[] = cancelledChanges) => {
    retain(cancelled, held)
    onFieldEdit("change", serializeArgs({ ...args, changes: next }).change)
  }
  const cancel = (ids: Iterable<string>) => {
    const edit = cancelLinks(args, rows, new Set(ids))
    saveEntries(edit.entries, { entries: edit.departed, rows: edit.dropped })
  }
  // A summary line filters the change table, across every target.
  const lineFor = (
    id: string,
    label: string,
    match: (row: LinkRow) => boolean,
    extra: Partial<ChangeSummaryLine> = {}
  ): ChangeSummaryLine => ({
    count: live.filter(match).length,
    id,
    label,
    onSelect: () => {
      setTarget(null)
      setTab(id)
    },
    selected: tab === id,
    ...extra,
  })

  return (
    <div className="grid min-w-0 gap-3">
      <ChangeBanner
        detail={[
          parents.length > 0
            ? `${parents.length.toLocaleString("en-GB")} ${parents.length === 1 ? "target" : "targets"}`
            : null,
          parents.length > 0 ? "Assets are added alongside what each one has" : null,
          changes.length > 0 ? "Edited assets change everywhere they're used" : null,
        ]
          .filter(Boolean)
          .join(" · ")}
      />
      <ProblemList problems={assetLimitProblems(args)} />
      {(["SITELINK", "CALLOUT"] as const).map((type) => {
        const assets = newAssets.filter((row) => row.assetType === type)
        if (assets.length === 0) return null
        return (
          <section key={type} aria-label={NEW_ASSET_TITLES[type]} className="grid gap-2">
            <h3 className="text-sm font-medium">
              {NEW_ASSET_TITLES[type]}{" "}
              <span className="text-muted-foreground tabular-nums">{String(assets.length)}</span>
            </h3>
            <NewAssetTable
              disabled={disabled}
              onCancel={(at) => {
                const key = assets[at]?.key
                cancel(live.filter((row) => row.assetKey === key).map((row) => row.id))
              }}
              onEdit={(at, field, value) => {
                const edit = editNewAsset(args, cancelled.rows, assets[at]?.key ?? "", field, value)
                saveEntries(edit.entries, NOTHING_LEFT, { ...cancelled, rows: edit.rows })
              }}
              rows={assets.map((row, at) => ({
                asset: row.value,
                label: `${ASSET_TYPE_LABELS[type]} ${String(at + 1)}`,
                problem: row.problem,
                targets: row.targets,
              }))}
              type={type}
            />
          </section>
        )
      })}
      {newAssets.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {(["campaign", "ad_group"] as const).map((kind) => (
            <div key={kind} className="w-64">
              <EntityPicker
                currentLabel={null}
                disabled={disabled}
                entityKind={kind === "campaign" ? "google_ads_campaign" : "google_ads_ad_group"}
                fieldKey="entries"
                label={kind === "campaign" ? "Add Campaign" : "Add Ad Group"}
                onChoose={(value) => {
                  saveEntries(addTarget(args, kind, value))
                }}
                toolName={TOOL}
              />
            </div>
          ))}
        </div>
      ) : null}
      {rows.length >= TOOLS_FROM ? (
        <>
          <ChangeSummary
            lines={[
              lineFor("already_set", "Already Linked", (row) => row.state === "already_set", {
                detail: "skipped, nothing changes",
              }),
              lineFor("not_found", "Not There to Remove", (row) => row.state === "not_found", {
                detail: "skipped, nothing changes",
              }),
              lineFor("attention", "Needs Attention", (row) => row.problem !== null, {
                tone: "danger",
                action: (
                  <Button
                    disabled={disabled}
                    onClick={() => {
                      cancel(blocked.map((row) => row.id))
                    }}
                    size="sm"
                    type="button"
                    variant="outline"
                  >
                    Cancel These {String(blocked.length)}
                  </Button>
                ),
              }),
            ]}
          />
          <AttentionLine
            count={blocked.length}
            onShow={() => {
              setTarget(null)
              setTab("attention")
            }}
          />
        </>
      ) : null}
      {parents.length > 0 ? (
        <ParentTable
          columns={PARENT_COLUMNS}
          disabled={disabled}
          label="Campaigns and Ad Groups"
          onCancel={(key) => {
            cancel(live.filter((row) => row.targetKey === key).map((row) => row.id))
          }}
          onSelect={setTarget}
          onUndo={(key) => {
            saveEntries(
              restoreParent(ASSET_CANCEL_CARD, args.entries, cancelled.entries, rows, key)
            )
          }}
          rowNoun={["target", "targets"]}
          rows={parents}
          selected={target}
        />
      ) : null}
      {shown.length > 0 ? (
        <LinkTable
          disabled={disabled}
          onCancel={cancel}
          onTabChange={setTab}
          onUndo={(row) => {
            saveEntries(restoreRow(ASSET_CANCEL_CARD, args.entries, cancelled.entries, row))
          }}
          rows={shown}
          showTarget={target === null && parents.length > 1}
          tab={tab}
        />
      ) : null}
      {changes.length > 0 ? (
        <section aria-label="Edit Assets" className="grid gap-2">
          <h3 className="text-sm font-medium">Edit Assets</h3>
          {changes.map((change) => (
            <ChangeCard
              key={change.key}
              change={change}
              disabled={disabled}
              onCancel={() => {
                saveChanges(
                  args.changes.filter((item) => item.key !== change.key),
                  [...cancelledChanges, change]
                )
              }}
              onEdit={(field, value) => {
                saveChanges(editChange(args, change.key, field, value))
              }}
              onUndo={() => {
                saveChanges(
                  [...args.changes, change],
                  cancelledChanges.filter((item) => item.key !== change.key)
                )
              }}
            />
          ))}
        </section>
      ) : null}
      {needsCheck(args, checked) && counts.total > 0 ? (
        <CheckChanges
          canCheck={canCheckAssets(args)}
          disabled={disabled}
          label={checkIncomplete(checked) ? "Check Again" : "Check Changes"}
          note="You changed this request, so Google needs to check it again."
          onCheck={controls.onReview}
          submitting={controls.submitting}
        />
      ) : null}
    </div>
  )
}

function linkChange(row: LinkRow): string {
  if (row.action === "remove") return "Remove"
  return row.isNew ? "Add New" : "Add"
}

function linkTabs(byId: ReadonlyMap<string, LinkRow>): DataTableTab[] {
  const live = (row: DataRow, match: (link: LinkRow) => boolean) => {
    const link = byId.get(String(row["key"]))
    return link !== undefined && !link.cancelled && match(link)
  }
  return [
    { id: "all", label: "All", match: () => true },
    {
      hideWhenEmpty: true,
      id: "already_set",
      label: "Already Linked",
      match: (row) => live(row, (link) => link.state === "already_set"),
    },
    {
      hideWhenEmpty: true,
      id: "not_found",
      label: "Not There",
      match: (row) => live(row, (link) => link.state === "not_found"),
    },
    {
      hideWhenEmpty: true,
      id: "attention",
      label: "Needs Attention",
      match: (row) => live(row, (link) => link.problem !== null),
    },
  ]
}

/** One row per asset and target, with filters and a bulk bar once the request is long. */
function LinkTable({
  disabled,
  onCancel,
  onTabChange,
  onUndo,
  rows,
  showTarget,
  tab,
}: {
  disabled: boolean
  onCancel: (ids: Iterable<string>) => void
  onTabChange: (id: string) => void
  onUndo: (row: LinkRow) => void
  rows: readonly LinkRow[]
  // The targets table names a selected target, so the column is for rows of them all.
  showTarget: boolean
  tab: string
}) {
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set())
  const byId = useMemo(() => new Map(rows.map((row) => [row.id, row])), [rows])
  const tabs = useMemo(() => linkTabs(byId), [byId])
  const columns = useMemo(
    () => LINK_COLUMNS.filter((column) => showTarget || column.key !== "target"),
    [showTarget]
  )
  const tableRows: DataRow[] = rows.map((row) => ({
    asset: row.label,
    cancel: "",
    change: linkChange(row),
    key: row.id,
    target: row.targetName,
    type: ASSET_TYPE_LABELS[row.assetType],
  }))
  return (
    <DataTable
      activeTab={tab}
      columns={columns}
      exportFilename="google-ads-asset-changes.csv"
      onTabChange={onTabChange}
      pageSize={10}
      renderCell={(column, row) => {
        const link = byId.get(String(row["key"]))
        if (!link) return null
        if (column.key === "asset")
          return (
            <span className="grid min-w-0 gap-0.5 text-sm whitespace-normal">
              <span className={cn("font-medium wrap-anywhere", link.cancelled && "line-through")}>
                {link.label}
              </span>
              {!link.cancelled && link.problem ? (
                <span className="text-destructive text-xs wrap-anywhere">{link.problem}</span>
              ) : null}
            </span>
          )
        if (column.key === "change") {
          if (link.cancelled)
            return <span className="text-sm line-through">{linkChange(link)}</span>
          if (link.state === "already_set") return <Badge variant="secondary">Already Linked</Badge>
          if (link.state === "not_found") return <Badge variant="secondary">Not There</Badge>
          return (
            <Badge variant={link.action === "add" ? "success" : "warning"}>
              {linkChange(link)}
            </Badge>
          )
        }
        if (column.key === "target")
          return <span className="text-sm wrap-anywhere whitespace-normal">{link.targetName}</span>
        if (column.key === "cancel")
          return (
            <CancelCell
              cancelled={link.cancelled}
              disabled={disabled}
              onCancel={() => {
                onCancel([link.id])
              }}
              onUndo={() => {
                onUndo(link)
              }}
            />
          )
        return null
      }}
      rowClassName={(row) => (byId.get(String(row["key"]))?.cancelled ? "opacity-60" : undefined)}
      rowDetails={false}
      rowNoun={["change", "changes"]}
      rows={tableRows}
      {...(rows.length >= TOOLS_FROM
        ? {
            searchable: true,
            selection: {
              actions: (
                <Button
                  disabled={disabled}
                  onClick={() => {
                    onCancel(selected)
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
              rowId: (row) => String(row["key"]),
              selected,
            },
            tabs,
          }
        : {})}
    />
  )
}

// Where the edit seam holds each field of an asset's live content.
const LIVE_PATHS: Record<string, string> = {
  description1: "sitelinkAsset.description1",
  description2: "sitelinkAsset.description2",
  final_url: "finalUrls",
  link_text: "sitelinkAsset.linkText",
  text: "calloutAsset.calloutText",
}

function nowText(before: Record<string, unknown> | null, key: string): string | null {
  if (before === null) return null
  const value = before[LIVE_PATHS[key] ?? ""]
  if (Array.isArray(value)) return typeof value[0] === "string" ? value[0] : null
  return typeof value === "string" ? value : null
}

/** One existing asset's new content, with what it says now and where it's used. */
function ChangeCard({
  change,
  disabled,
  onCancel,
  onEdit,
  onUndo,
}: {
  change: ChangeRow
  disabled: boolean
  onCancel: () => void
  onEdit: (field: string, value: string) => void
  onUndo: () => void
}) {
  const more = change.useCount - change.usedIn.length
  const group = change.assetType === "SITELINK" ? "sitelinkAsset" : "calloutAsset"
  const dates = assetDatesText(change.content["start_date"], change.content["end_date"])
  const datesNow = assetDatesText(
    change.before?.[`${group}.startDate`],
    change.before?.[`${group}.endDate`]
  )
  return (
    <div className={cn("grid gap-2 rounded-lg border px-3 py-2", change.cancelled && "opacity-60")}>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className={cn("font-medium", change.cancelled && "line-through")}>
          {change.ref.label}
        </span>
        <Badge variant="secondary">{ASSET_TYPE_LABELS[change.assetType]}</Badge>
        {change.state === "already_set" ? <Badge variant="secondary">Already Set</Badge> : null}
        <span className="ml-auto">
          <CancelCell
            cancelled={change.cancelled}
            disabled={disabled}
            onCancel={onCancel}
            onUndo={onUndo}
          />
        </span>
      </div>
      {change.cancelled ? null : (
        <>
          {change.usedIn.length > 0 ? (
            <p className="text-muted-foreground text-xs wrap-anywhere">
              Used in {change.usedIn.join(", ")}
              {more > 0 ? ` and ${String(more)} more` : ""}
            </p>
          ) : null}
          {change.accountLevel ? (
            <p className="text-warning-text text-xs">
              Also used across the whole account, so this edit shows on every campaign without its
              own {ASSET_TYPE_LABELS[change.assetType].toLowerCase()}s.
            </p>
          ) : null}
          <div className="grid gap-2 sm:grid-cols-2">
            {ASSET_FIELDS[change.assetType].map((field) => {
              const now = nowText(change.before, field.key)
              const value = change.content[field.key]
              return (
                <label key={field.key} className="grid gap-1 text-xs">
                  <span className="text-muted-foreground">
                    {field.label}
                    {now !== null ? ` · Now: ${now}` : ""}
                  </span>
                  <AssetFieldInput
                    disabled={disabled}
                    field={field}
                    label={`${field.label} for ${change.ref.label}`}
                    onCommit={(next) => {
                      onEdit(field.key, next)
                    }}
                    value={typeof value === "string" ? value : ""}
                  />
                </label>
              )
            })}
          </div>
          {dates || datesNow ? (
            <p className="text-muted-foreground text-xs">
              Shows: {dates ?? "Any Time"}
              {change.before ? ` · Now: ${datesNow ?? "Any Time"}` : ""}
            </p>
          ) : null}
          {change.problem ? (
            <p className="text-destructive text-sm wrap-anywhere">{change.problem}</p>
          ) : null}
        </>
      )}
    </div>
  )
}
