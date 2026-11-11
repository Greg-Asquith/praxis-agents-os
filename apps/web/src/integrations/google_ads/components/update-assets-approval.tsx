// apps/web/src/integrations/google_ads/components/update-assets-approval.tsx

import { useMemo, useState } from "react"

import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-types"
import type { EditedValue } from "@/components/tool-ui/edited-values"
import { Badge } from "@/components/ui/badge"
import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"
import { CancelCell } from "@/integrations/ads/components/cancel-cell"
import { ChangeBanner } from "@/integrations/ads/components/change-banner"
import { EntityPicker } from "@/integrations/ads/components/entity-picker"
import { ParentTable } from "@/integrations/ads/components/parent-table"
import { CheckChanges } from "@/integrations/google_ads/components/check-changes"
import { AssetFieldInput } from "@/integrations/google_ads/components/new-assets-editor"
import {
  addTarget,
  ASSET_TYPE_LABELS,
  assetCounts,
  assetParents,
  CALLOUT_FIELDS,
  cancelLinks,
  changeRows,
  editChange,
  editNewAsset,
  linkRows,
  needsCheck,
  newAssetRows,
  parseCancelled,
  restoreLink,
  restoreTarget,
  serializeArgs,
  serializeCancelled,
  SITELINK_FIELDS,
  type AssetField,
  type AssetTarget,
  type AssetType,
  type ChangeRow,
  type LinkRow,
  type NewAssetRow,
  type UpdateAssetsArgs,
} from "@/integrations/google_ads/lib/update-assets"
import { cn } from "@/lib/utils"

const TOOL = "google_ads_update_assets"

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
  { key: "target", kind: "text", label: "Where", width: 220, hidden: true },
  { key: "cancel", kind: "text", label: "Cancel", width: 70 },
]

const FIELDS: Record<AssetType, readonly AssetField[]> = {
  CALLOUT: CALLOUT_FIELDS,
  SITELINK: SITELINK_FIELDS,
}

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
  const cancelled = useMemo(() => parseCancelled(controls.retained), [controls.retained])
  const rows = useMemo(
    () => linkRows(args, checked, cancelled.rows),
    [args, checked, cancelled.rows]
  )
  const changes = useMemo(() => changeRows(args, checked), [args, checked])
  const counts = assetCounts(rows, changes)
  const [target, setTarget] = useState<string | null>(null)
  const accountCount = new Set(rows.map((row) => row.targetKey.split("/")[1])).size
  const parents = useMemo(
    () => assetParents(args, rows, accountCount > 1),
    [accountCount, args, rows]
  )
  const newAssets = newAssetRows(rows, args)
  const shown = target === null ? rows : rows.filter((row) => row.targetKey === target)

  // A link or target that leaves the request stays beside it, so Undo can restore it.
  const saveEntries = (
    next: AssetTarget[],
    dropped: readonly LinkRow[] = [],
    departed: readonly AssetTarget[] = []
  ) => {
    const kept = new Set(next.map((entry) => entry.key))
    const live = new Set(linkRows({ ...args, entries: next }, checked).map((row) => row.id))
    controls.onRetain?.(
      serializeCancelled({
        entries: [
          ...cancelled.entries.filter((entry) => !kept.has(entry.key)),
          ...departed.filter((entry) => !kept.has(entry.key)),
        ],
        rows: [...cancelled.rows, ...dropped].filter((row) => !live.has(row.id)),
      })
    )
    onFieldEdit("entries", serializeArgs({ ...args, entries: next }).entries)
  }
  const cancel = (ids: Iterable<string>) => {
    const edit = cancelLinks(args, rows, new Set(ids))
    saveEntries(edit.entries, edit.dropped, edit.departed)
  }
  const cancelAsset = (key: string) => {
    cancel(rows.filter((row) => row.assetKey === key && !row.cancelled).map((row) => row.id))
  }
  const sitelinks = newAssets.filter((row) => row.assetType === "SITELINK")
  const callouts = newAssets.filter((row) => row.assetType === "CALLOUT")

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
      {sitelinks.length > 0 ? (
        <NewAssetTable
          disabled={disabled}
          onCancel={cancelAsset}
          onEdit={(key, field, value) => {
            saveEntries(editNewAsset(args, key, field, value))
          }}
          rows={sitelinks}
          title="New Sitelinks"
          type="SITELINK"
        />
      ) : null}
      {callouts.length > 0 ? (
        <NewAssetTable
          disabled={disabled}
          onCancel={cancelAsset}
          onEdit={(key, field, value) => {
            saveEntries(editNewAsset(args, key, field, value))
          }}
          rows={callouts}
          title="New Callouts"
          type="CALLOUT"
        />
      ) : null}
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
      {parents.length > 0 ? (
        <ParentTable
          columns={PARENT_COLUMNS}
          disabled={disabled}
          label="Campaigns and Ad Groups"
          onCancel={(key) => {
            cancel(rows.filter((row) => row.targetKey === key).map((row) => row.id))
          }}
          onSelect={setTarget}
          onUndo={(key) => {
            saveEntries(restoreTarget(args, cancelled.entries, rows, key))
          }}
          rowNoun={["target", "targets"]}
          rows={parents}
          selected={target}
        />
      ) : null}
      {shown.length > 0 ? (
        <LinkTable
          disabled={disabled}
          onCancel={(id) => {
            cancel([id])
          }}
          onUndo={(row) => {
            saveEntries(restoreLink(args, cancelled.entries, row))
          }}
          rows={shown}
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
              onEdit={(field, value) => {
                onFieldEdit(
                  "change",
                  serializeArgs({
                    ...args,
                    changes: editChange(args, change.key, field, value),
                  }).change
                )
              }}
            />
          ))}
        </section>
      ) : null}
      {needsCheck(args, checked) && counts.total > 0 ? (
        <CheckChanges
          canCheck
          disabled={disabled}
          label={
            [...checked.checks.values(), ...checked.changeChecks.values()].some(
              (check) => check.unavailable
            )
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

function fieldValue(value: Record<string, unknown>, key: string): string {
  const field = value[key]
  return typeof field === "string" ? field : ""
}

function NewAssetTable({
  disabled,
  onCancel,
  onEdit,
  rows,
  title,
  type,
}: {
  disabled: boolean
  onCancel: (key: string) => void
  onEdit: (key: string, field: string, value: string) => void
  rows: readonly NewAssetRow[]
  title: string
  type: AssetType
}) {
  const fields = FIELDS[type]
  const byKey = useMemo(() => new Map(rows.map((row) => [row.key, row])), [rows])
  const columns = useMemo<DataColumn[]>(
    () => [
      ...fields.map((field) => ({
        key: field.key,
        kind: "text" as const,
        label: field.label,
        width: field.key === "final_url" ? 220 : 180,
      })),
      { key: "targets", kind: "number", label: "Targets", width: 90 },
      { key: "cancel", kind: "text", label: "Cancel", width: 70 },
    ],
    [fields]
  )
  return (
    <section aria-label={title} className="grid gap-2">
      <h3 className="text-sm font-medium">
        {title} <span className="text-muted-foreground tabular-nums">{String(rows.length)}</span>
      </h3>
      <DataTable
        columns={columns}
        pageSize={10}
        renderCell={(column, row) => {
          const asset = byKey.get(String(row["key"]))
          if (!asset) return null
          if (column.key === "cancel")
            return (
              <CancelCell
                cancelled={false}
                disabled={disabled}
                onCancel={() => {
                  onCancel(asset.key)
                }}
                onUndo={() => undefined}
              />
            )
          if (column.key === "targets") return null
          const field = fields.find((item) => item.key === column.key)
          if (!field) return null
          const first = field === fields[0]
          return (
            <span className="grid gap-1 whitespace-normal">
              <AssetFieldInput
                key={`${asset.key}|${field.key}`}
                disabled={disabled}
                field={field}
                label={`${field.label} for ${fieldValue(asset.value, fields[0]?.key ?? "") || ASSET_TYPE_LABELS[type]}`}
                onCommit={(value) => {
                  onEdit(asset.key, field.key, value)
                }}
                value={fieldValue(asset.value, field.key)}
              />
              {first && asset.problem ? (
                <span className="text-destructive text-xs wrap-anywhere">{asset.problem}</span>
              ) : null}
            </span>
          )
        }}
        rowDetails={false}
        rowNoun={[
          ASSET_TYPE_LABELS[type].toLowerCase(),
          `${ASSET_TYPE_LABELS[type].toLowerCase()}s`,
        ]}
        rows={rows.map((row) => ({ key: row.key, targets: row.targets }))}
      />
    </section>
  )
}

function linkChange(row: LinkRow): string {
  if (row.action === "remove") return "Remove"
  return row.isNew ? "Add New" : "Add"
}

function LinkTable({
  disabled,
  onCancel,
  onUndo,
  rows,
}: {
  disabled: boolean
  onCancel: (id: string) => void
  onUndo: (row: LinkRow) => void
  rows: readonly LinkRow[]
}) {
  const byId = useMemo(() => new Map(rows.map((row) => [row.id, row])), [rows])
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
      columns={LINK_COLUMNS}
      exportFilename="google-ads-asset-changes.csv"
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
        if (column.key === "cancel")
          return (
            <CancelCell
              cancelled={link.cancelled}
              disabled={disabled}
              onCancel={() => {
                onCancel(link.id)
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
    />
  )
}

function nowText(before: Record<string, unknown> | null, key: string): string | null {
  if (before === null) return null
  const paths: Record<string, string> = {
    description1: "sitelinkAsset.description1",
    description2: "sitelinkAsset.description2",
    final_url: "finalUrls",
    link_text: "sitelinkAsset.linkText",
    text: "calloutAsset.calloutText",
  }
  const value = before[paths[key] ?? ""]
  if (Array.isArray(value)) return typeof value[0] === "string" ? value[0] : null
  return typeof value === "string" ? value : null
}

/** One existing asset's new content, with what it says now and where it's used. */
function ChangeCard({
  change,
  disabled,
  onEdit,
}: {
  change: ChangeRow
  disabled: boolean
  onEdit: (field: string, value: string) => void
}) {
  const fields = FIELDS[change.assetType]
  const more = change.useCount - change.usedIn.length
  return (
    <div className="grid gap-2 rounded-lg border px-3 py-2">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium">{change.ref.label}</span>
        <Badge variant="secondary">{ASSET_TYPE_LABELS[change.assetType]}</Badge>
        {change.state === "already_set" ? <Badge variant="secondary">Already Set</Badge> : null}
      </div>
      {change.usedIn.length > 0 ? (
        <p className="text-muted-foreground text-xs wrap-anywhere">
          Used in {change.usedIn.join(", ")}
          {more > 0 ? ` and ${String(more)} more` : ""}
        </p>
      ) : null}
      <div className="grid gap-2 sm:grid-cols-2">
        {fields.map((field) => {
          const now = nowText(change.before, field.key)
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
                onCommit={(value) => {
                  onEdit(field.key, value)
                }}
                value={fieldValue(change.content, field.key)}
              />
            </label>
          )
        })}
      </div>
      {change.problem ? (
        <p className="text-destructive text-sm wrap-anywhere">{change.problem}</p>
      ) : null}
    </div>
  )
}
