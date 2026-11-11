// apps/web/src/integrations/google_ads/components/new-assets-editor.tsx

import { PlusIcon } from "lucide-react"
import { useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import { DataTable, type DataColumn } from "@/components/ui/data-table"
import { Input } from "@/components/ui/input"
import { CancelCell } from "@/integrations/ads/components/cancel-cell"
import { characterCount } from "@/integrations/google_ads/lib/create-ads"
import {
  assetLabels,
  blankAsset,
  draftAssetType,
  sitelinkAdvice,
  type DraftAsset,
} from "@/integrations/google_ads/lib/new-assets"
import {
  ASSET_TYPE_LABELS,
  CALLOUT_FIELDS,
  fieldProblem,
  SITELINK_FIELDS,
  type AssetField,
  type AssetType,
} from "@/integrations/google_ads/lib/update-assets"
import { cn } from "@/lib/utils"

const FIELDS: Record<AssetType, readonly AssetField[]> = {
  CALLOUT: CALLOUT_FIELDS,
  SITELINK: SITELINK_FIELDS,
}

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

function fieldText(asset: DraftAsset, key: string): string {
  const value = asset[key]
  return typeof value === "string" ? value : ""
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
  const advice = sitelinkAdvice(assets)
  return (
    <div className="grid min-w-0 gap-3">
      {(["SITELINK", "CALLOUT"] as const).map((type) => (
        <AssetTypeTable
          key={type}
          assets={assets}
          disabled={disabled}
          onChange={onChange}
          type={type}
        />
      ))}
      {advice ? <p className="text-muted-foreground text-xs">{advice}</p> : null}
    </div>
  )
}

function AssetTypeTable({
  assets,
  disabled,
  onChange,
  type,
}: {
  assets: readonly DraftAsset[]
  disabled: boolean
  onChange: (assets: DraftAsset[]) => void
  type: AssetType
}) {
  const fields = FIELDS[type]
  const noun = ASSET_TYPE_LABELS[type]
  const labels = assetLabels(assets)
  // Positions in the whole list, so an edit lands on the right asset.
  const positions = assets.flatMap((asset, index) =>
    draftAssetType(asset) === type ? [index] : []
  )
  const columns = useMemo<DataColumn[]>(
    () => [
      ...fields.map((field) => ({
        key: field.key,
        kind: "text" as const,
        label: field.label,
        width: field.key === "final_url" ? 220 : 170,
      })),
      { key: "cancel", kind: "text", label: "Cancel", width: 70 },
    ],
    [fields]
  )
  const edit = (index: number, key: string, value: string) => {
    onChange(assets.map((asset, at) => (at === index ? { ...asset, [key]: value } : asset)))
  }
  return (
    <section aria-label={`${noun}s`} className="grid min-w-0 gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium">
          {noun}s <span className="text-muted-foreground tabular-nums">{positions.length}</span>
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
        <DataTable
          columns={columns}
          pageSize={10}
          renderCell={(column, row) => {
            const index = Number(row["key"])
            const asset = assets[index]
            if (!asset) return null
            const label = labels[index] ?? noun
            if (column.key === "cancel")
              return (
                <CancelCell
                  cancelled={false}
                  disabled={disabled}
                  onCancel={() => {
                    onChange(assets.filter((_, at) => at !== index))
                  }}
                  onUndo={() => undefined}
                />
              )
            const field = fields.find((item) => item.key === column.key)
            if (!field) return null
            const problem = field === fields[0] ? fieldProblem(asset) : null
            return (
              <span className="grid gap-1 whitespace-normal">
                <AssetFieldInput
                  key={`${String(index)}|${field.key}`}
                  disabled={disabled}
                  field={field}
                  label={`${field.label} for ${label}`}
                  onCommit={(value) => {
                    edit(index, field.key, value)
                  }}
                  value={fieldText(asset, field.key)}
                />
                {problem ? (
                  <span className="text-destructive text-xs wrap-anywhere">{problem}</span>
                ) : null}
              </span>
            )
          }}
          rowDetails={false}
          rowNoun={[noun.toLowerCase(), `${noun.toLowerCase()}s`]}
          rows={positions.map((index) => ({ key: String(index) }))}
        />
      ) : null}
    </section>
  )
}
