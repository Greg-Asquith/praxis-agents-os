// apps/web/src/integrations/google_ads/components/new-assets-editor.tsx

import { PlusIcon, XIcon } from "lucide-react"
import { useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import { DataTable, type DataColumn } from "@/components/ui/data-table"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
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
  MAX_OFFERINGS,
  OFFERING_TEXT_LIMIT,
  offeringList,
  PRICE_UNITS,
  sitelinkAdvice,
  textList,
  type AssetField,
  type AssetType,
  type DraftAsset,
} from "@/integrations/google_ads/lib/new-assets"
import { cn } from "@/lib/utils"

/** One asset field: a choice, a comma-separated list, or text with its count against Google's limit. */
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
  onCommit: (value: unknown) => void
  value: unknown
}) {
  if (field.kind === "choice")
    return (
      <Select<string>
        disabled={disabled}
        onValueChange={(next) => {
          if (next !== null) onCommit(next || null)
        }}
        value={typeof value === "string" ? value : ""}
      >
        <SelectTrigger aria-label={label} className="w-full" size="sm">
          <SelectValue placeholder={`Choose ${field.label}`} />
        </SelectTrigger>
        <SelectContent align="start">
          <SelectGroup>
            {field.options.map((option) => (
              <SelectItem key={option.value} label={option.label} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>
    )
  if (field.kind === "list") {
    const items = textList(value)
    return (
      <TextInput
        counter={`${String(items.length)} of ${String(field.max)}`}
        disabled={disabled}
        invalid={
          items.length > field.max || items.some((item) => characterCount(item) > field.limit)
        }
        label={label}
        onCommit={(next) => {
          onCommit(
            next
              .split(",")
              .map((item) => item.trim())
              .filter(Boolean)
          )
        }}
        value={items.join(", ")}
      />
    )
  }
  const text = typeof value === "string" ? value : ""
  const length = characterCount(text.trim())
  // Counts help only for ad copy; codes and numbers have their own checks.
  const showCount = field.limit >= 25 && field.limit <= 35 && field.key !== "phone_number"
  return (
    <TextInput
      counter={showCount ? `${String(length)} of ${String(field.limit)}` : null}
      disabled={disabled}
      invalid={length > field.limit}
      label={label}
      limit={showCount ? field.limit : null}
      onCommit={onCommit}
      value={text}
    />
  )
}

/** A text input that commits on blur, with an optional live count under it. */
function TextInput({
  counter,
  disabled,
  invalid,
  label,
  limit = null,
  onCommit,
  value,
}: {
  counter: string | null
  disabled: boolean
  invalid: boolean
  label: string
  // Recounts the draft as it's typed when set; otherwise the count shows the committed value.
  limit?: number | null
  onCommit: (value: string) => void
  value: string
}) {
  const [draft, setDraft] = useState<string | null>(null)
  const text = draft ?? value
  const length = characterCount(text.trim())
  const over = limit !== null ? length > limit : invalid
  const count = limit !== null ? `${String(length)} of ${String(limit)}` : counter
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
      {count ? (
        <span
          className={cn(
            "text-xs tabular-nums",
            over ? "text-destructive font-medium" : "text-muted-foreground"
          )}
        >
          {count}
        </span>
      ) : null}
    </span>
  )
}

const OFFERING_FIELDS = [
  { key: "header", label: "Header" },
  { key: "description", label: "Description" },
  { key: "price", label: "Price" },
  { key: "unit", label: "Unit" },
  { key: "final_url", label: "Final URL" },
] as const

const UNIT_FIELD: AssetField = {
  key: "unit",
  kind: "choice",
  label: "Unit",
  options: PRICE_UNITS,
  optional: true,
}

/** A price's items, a row each, with every field editable and items added up to Google's limit. */
export function PriceOfferingsEditor({
  currency,
  disabled,
  label,
  onChange,
  value,
}: {
  currency: string
  disabled: boolean
  // Names the price for a screen reader, such as "Price 1".
  label: string
  onChange: (offerings: Record<string, unknown>[]) => void
  value: unknown
}) {
  const offerings = offeringList(value)
  const edit = (at: number, key: string, next: unknown) => {
    onChange(offerings.map((item, index) => (index === at ? { ...item, [key]: next } : item)))
  }
  return (
    <div className="grid min-w-0 gap-2">
      <Table>
        <TableHeader>
          <TableRow>
            {OFFERING_FIELDS.map((field) => (
              <TableHead key={field.key}>
                {field.key === "price" && currency ? `Price (${currency})` : field.label}
              </TableHead>
            ))}
            <TableHead>
              <span className="sr-only">Remove</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {offerings.map((offering, at) => {
            const name = `item ${String(at + 1)} of ${label}`
            return (
              // Keyed by position and header, since items have no ID and an edit changes the rest.
              <TableRow
                key={`${String(at)}|${typeof offering["header"] === "string" ? offering["header"] : ""}`}
              >
                {OFFERING_FIELDS.map((field) => (
                  <TableCell
                    key={field.key}
                    className={cn("align-top", field.key === "final_url" ? "min-w-48" : "min-w-28")}
                  >
                    <AssetFieldInput
                      disabled={disabled}
                      field={
                        field.key === "unit"
                          ? UNIT_FIELD
                          : {
                              key: field.key,
                              kind: "text",
                              label: field.label,
                              limit:
                                field.key === "header" || field.key === "description"
                                  ? OFFERING_TEXT_LIMIT
                                  : 2048,
                            }
                      }
                      label={`${field.label} for ${name}`}
                      onCommit={(next) => {
                        edit(at, field.key, next)
                      }}
                      value={offering[field.key] ?? ""}
                    />
                  </TableCell>
                ))}
                <TableCell className="align-top">
                  <Button
                    aria-label={`Remove ${name}`}
                    disabled={disabled}
                    onClick={() => {
                      onChange(offerings.filter((_, index) => index !== at))
                    }}
                    size="icon-sm"
                    type="button"
                    variant="ghost"
                  >
                    <XIcon />
                  </Button>
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
      {offerings.length < MAX_OFFERINGS ? (
        <Button
          className="justify-self-start"
          disabled={disabled}
          onClick={() => {
            onChange([
              ...offerings,
              { description: "", final_url: "", header: "", price: "", unit: null },
            ])
          }}
          size="sm"
          type="button"
          variant="outline"
        >
          <PlusIcon />
          Add Item
        </Button>
      ) : null}
    </div>
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
  onEdit: (index: number, field: string, value: unknown) => void
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
        width: field.key === "final_url" || field.kind === "list" ? 240 : 170,
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
              value={row.asset[field.key]}
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
