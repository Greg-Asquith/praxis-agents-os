// apps/web/src/integrations/google_ads/components/new-assets-editor.tsx

import { PlusIcon } from "lucide-react"
import { useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import { DataTable, type DataColumn } from "@/components/ui/data-table"
import { Input } from "@/components/ui/input"
import { CancelCell } from "@/integrations/ads/components/cancel-cell"
import { characterCount } from "@/integrations/google_ads/lib/create-ads"
import {
  ASSET_FIELDS,
  ASSET_TYPE_LABELS,
  assetDatesText,
  assetLabels,
  blankAsset,
  draftAssetType,
  fieldProblem,
  sitelinkAdvice,
  type AssetField,
  type AssetType,
  type DraftAsset,
} from "@/integrations/google_ads/lib/new-assets"
import { cn } from "@/lib/utils"

/** A text field that commits on blur and shows its count against Google's limit. */
export function AssetFieldInput({
  disabled,
  field,
  label,
  onCommit,
  value,
}: {
  disabled: boolean
  field: AssetField
  label: string
  onCommit: (value: string) => void
  value: string
}) {
  const [draft, setDraft] = useState<string | null>(null)
  const text = draft ?? value
  const length = characterCount(text.trim())
  const over = length > field.limit
  const showCount = field.limit <= 35
  return (
    <span className="grid min-w-0 gap-0.5">
      <Input
        aria-invalid={over}
        aria-label={label}
        className="h-8 text-sm"
        disabled={disabled}
        onBlur={() => {
          setDraft(null)
          if (draft !== null && draft !== value) onCommit(draft)
        }}
        onChange={(event) => {
          setDraft(event.currentTarget.value)
        }}
        value={text}
      />
      {showCount ? (
        <span
          className={cn(
            "text-xs tabular-nums",
            over ? "text-destructive font-medium" : "text-muted-foreground"
          )}
        >
          {String(length)} of {String(field.limit)}
        </span>
      ) : null}
    </span>
  )
}

export type AssetTableRow = {
  asset: DraftAsset
  // Names the row for a screen reader, such as "Sitelink 2".
  label: string
  problem: string | null
  // How many campaigns and ad groups get it, on a card that adds one asset to several.
  targets?: number
}

/** New sitelinks or callouts, a row each, with every field editable in place. */
export function NewAssetTable({
  disabled,
  onCancel,
  onEdit,
  rows,
  type,
}: {
  disabled: boolean
  // Rows are named by their position in `rows`.
  onCancel: (index: number) => void
  onEdit: (index: number, field: string, value: string) => void
  rows: readonly AssetTableRow[]
  type: AssetType
}) {
  const fields = ASSET_FIELDS[type]
  const noun = ASSET_TYPE_LABELS[type].toLowerCase()
  const dated = rows.some(
    (row) => assetDatesText(row.asset["start_date"], row.asset["end_date"]) !== null
  )
  const shared = rows.some((row) => row.targets !== undefined)
  const columns = useMemo<DataColumn[]>(
    () => [
      ...fields.map((field) => ({
        key: field.key,
        kind: "text" as const,
        label: field.label,
        width: field.key === "final_url" ? 220 : 170,
      })),
      ...(dated ? [{ key: "dates", kind: "text" as const, label: "Shows", width: 200 }] : []),
      ...(shared ? [{ key: "targets", kind: "number" as const, label: "Targets", width: 90 }] : []),
      { key: "cancel", kind: "text", label: "Cancel", width: 70 },
    ],
    [dated, fields, shared]
  )
  return (
    <DataTable
      columns={columns}
      pageSize={10}
      renderCell={(column, tableRow) => {
        const index = Number(tableRow["key"])
        const row = rows[index]
        if (!row) return null
        if (column.key === "cancel")
          return (
            <CancelCell
              cancelled={false}
              disabled={disabled}
              onCancel={() => {
                onCancel(index)
              }}
              onUndo={() => undefined}
            />
          )
        const field = fields.find((item) => item.key === column.key)
        if (!field) return null
        const value = row.asset[field.key]
        return (
          <span className="grid gap-1 whitespace-normal">
            <AssetFieldInput
              // Keyed by position, since an edit changes the asset's own key.
              key={`${String(index)}|${field.key}`}
              disabled={disabled}
              field={field}
              label={`${field.label} for ${row.label}`}
              onCommit={(next) => {
                onEdit(index, field.key, next)
              }}
              value={typeof value === "string" ? value : ""}
            />
            {field === fields[0] && row.problem ? (
              <span className="text-destructive text-xs wrap-anywhere">{row.problem}</span>
            ) : null}
          </span>
        )
      }}
      rowDetails={false}
      rowNoun={[noun, `${noun}s`]}
      rows={rows.map((row, index) => ({
        dates: assetDatesText(row.asset["start_date"], row.asset["end_date"]) ?? "",
        key: String(index),
        targets: row.targets ?? "",
      }))}
    />
  )
}

/** New sitelinks and callouts for one campaign or ad group, a table per type. */
export function NewAssetsEditor({
  assets,
  disabled,
  onChange,
}: {
  assets: readonly DraftAsset[]
  disabled: boolean
  onChange: (assets: DraftAsset[]) => void
}) {
  const labels = assetLabels(assets)
  const sitelinks = assets.filter((asset) => draftAssetType(asset) === "SITELINK").length
  const advice = sitelinks > 0 ? sitelinkAdvice(sitelinks) : null
  return (
    <div className="grid min-w-0 gap-3">
      {(["SITELINK", "CALLOUT"] as const).map((type) => {
        const noun = ASSET_TYPE_LABELS[type]
        // Positions in the whole list, so an edit lands on the right asset.
        const positions = assets.flatMap((asset, index) =>
          draftAssetType(asset) === type ? [index] : []
        )
        return (
          <section key={type} aria-label={`${noun}s`} className="grid min-w-0 gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-medium">
                {noun}s{" "}
                <span className="text-muted-foreground tabular-nums">{positions.length}</span>
              </p>
              <Button
                disabled={disabled}
                onClick={() => {
                  onChange([...assets, blankAsset(type)])
                }}
                size="sm"
                type="button"
                variant="outline"
              >
                <PlusIcon />
                Add {noun}
              </Button>
            </div>
            {positions.length > 0 ? (
              <NewAssetTable
                disabled={disabled}
                onCancel={(at) => {
                  onChange(assets.filter((_, index) => index !== positions[at]))
                }}
                onEdit={(at, key, value) => {
                  onChange(
                    assets.map((asset, index) =>
                      index === positions[at] ? { ...asset, [key]: value } : asset
                    )
                  )
                }}
                rows={positions.map((index) => ({
                  asset: assets[index] ?? {},
                  label: labels[index] ?? noun,
                  problem: fieldProblem(assets[index] ?? {}),
                }))}
                type={type}
              />
            ) : null}
          </section>
        )
      })}
      {advice ? <p className="text-muted-foreground text-xs">{advice}</p> : null}
    </div>
  )
}
