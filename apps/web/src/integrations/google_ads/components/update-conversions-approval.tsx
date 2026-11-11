// apps/web/src/integrations/google_ads/components/update-conversions-approval.tsx

import { InfoIcon } from "lucide-react"
import { useMemo, useState, type ReactNode } from "react"

import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-types"
import type { EditedValue } from "@/components/tool-ui/edited-values"
import { Badge } from "@/components/ui/badge"
import { DataTable, type DataColumn } from "@/components/ui/data-table"
import { AttentionLine } from "@/integrations/ads/components/attention-line"
import { CancelCell } from "@/integrations/ads/components/cancel-cell"
import { ChangeBanner } from "@/integrations/ads/components/change-banner"
import { CommittedInput } from "@/integrations/ads/components/committed-input"
import { SegmentedChoice } from "@/integrations/ads/components/controls"
import { AddChange } from "@/integrations/google_ads/components/add-change"
import { CheckChanges } from "@/integrations/google_ads/components/check-changes"
import {
  addableConversionSettings,
  addedConversionSetting,
  type CancelledConversionSetting,
  changesBidding,
  CONVERSION_SETTING_TITLES,
  conversionCounts,
  conversionCurrency,
  type ConversionRow,
  conversionRows,
  conversionsBannerDetail,
  type ConversionSetting,
  conversionsNeedCheck,
  type ConversionValue,
  conversionValueText,
  COUNTING_LABELS,
  COUNTINGS,
  editedConversions,
  parseCancelledConversionSettings,
  restoredConversions,
  STATUSES,
  type UpdateConversionsArgs,
  WINDOW_DAYS,
} from "@/integrations/google_ads/lib/update-conversions"

// Below this many changes the table tools only add noise.
const TOOLS_FROM = 10

const COLUMNS: DataColumn[] = [
  { key: "name", kind: "text", label: "Conversion Action", width: 220 },
  { key: "setting", kind: "text", label: "Setting", width: 190 },
  { key: "change", kind: "text", label: "Change", width: 300 },
  { key: "conversions", kind: "number", label: "Last 30 Days", width: 110 },
  { key: "cancel", kind: "text", label: "Cancel", width: 80 },
]

const CHOICES: Partial<Record<ConversionSetting, readonly { value: string; label: string }[]>> = {
  always_use_default_value: [
    { value: "true", label: "Yes" },
    { value: "false", label: "No" },
  ],
  biddable: [
    { value: "true", label: "Yes" },
    { value: "false", label: "No" },
  ],
  counting: COUNTINGS.map((value) => ({ value, label: COUNTING_LABELS[value] })),
  primary: [
    { value: "true", label: "Primary" },
    { value: "false", label: "Secondary" },
  ],
  status: STATUSES.map((value) => ({ value, label: value === "ENABLED" ? "Enabled" : "Hidden" })),
}

type Edit = (value: ConversionValue) => void
type Fields = ReturnType<typeof editedConversions>

export function UpdateConversionsApproval({
  args,
  checked,
  controls,
  disabled,
  onFieldEdit,
}: {
  args: UpdateConversionsArgs
  // The request Google last answered for.
  checked: UpdateConversionsArgs
  controls: ToolApprovalDecisionControls
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
}) {
  const [tab, setTab] = useState("all")
  const cancelled = useMemo(
    () => parseCancelledConversionSettings(controls.retained),
    [controls.retained]
  )
  const rows = useMemo(() => conversionRows(args, checked, cancelled), [args, checked, cancelled])
  const byId = useMemo(() => new Map(rows.map((row) => [row.id, row])), [rows])
  const counts = conversionCounts(rows)
  const tools = rows.length >= TOOLS_FROM

  // A review redraws the card, so cancelled settings live beside the request for Undo. Each
  // action edits one item, so only one of the two fields changes.
  const save = (next: Fields, nextCancelled: readonly CancelledConversionSetting[]) => {
    if (nextCancelled !== cancelled) controls.onRetain?.(nextCancelled)
    const current = editedConversions(args, new Set(), () => undefined)
    for (const field of ["changes", "account_goals"] as const)
      if (JSON.stringify(next[field]) !== JSON.stringify(current[field]))
        onFieldEdit(field, next[field])
  }
  const cancel = (row: ConversionRow) => {
    const field = row.kind === "goal" ? "goal" : "conversion_action"
    const reference = row.item?.entry[field]
    if (row.cancelled || !reference || typeof reference !== "object") return
    save(
      editedConversions(args, new Set([row.id]), () => undefined),
      [
        ...cancelled,
        {
          key: row.key,
          kind: row.kind,
          reference: reference as Record<string, unknown>,
          setting: row.setting,
          value: row.value,
        },
      ]
    )
  }
  const undo = (row: ConversionRow) => {
    const items = cancelled.filter((item) => `${item.key}|${item.setting}` === row.id)
    if (items.length > 0)
      save(
        restoredConversions(args, items),
        cancelled.filter((item) => !items.includes(item))
      )
  }
  const edit =
    (row: ConversionRow): Edit =>
    (value) => {
      save(
        editedConversions(args, new Set([row.id]), () => value),
        cancelled
      )
    }

  return (
    <div className="grid min-w-0 gap-3">
      <ChangeBanner
        aside={
          <p className="text-sm font-medium tabular-nums">
            {String(counts.apply)} {counts.apply === 1 ? "change" : "changes"}
          </p>
        }
        detail={conversionsBannerDetail(counts, args.accounts, args.items[0]?.customerId)}
        {...(changesBidding(rows)
          ? { title: "Bidding will optimise for different conversions" }
          : {})}
      />
      {tools ? (
        <AttentionLine
          count={counts.problems}
          onShow={() => {
            setTab("attention")
          }}
        />
      ) : null}
      <DataTable
        activeTab={tab}
        columns={COLUMNS}
        exportFilename="google-ads-conversion-changes.csv"
        onTabChange={setTab}
        pageSize={25}
        renderCell={(column, dataRow) => {
          const row = byId.get(String(dataRow["id"]))
          if (!row) return null
          if (column.key === "name") return <NameCell row={row} />
          if (column.key === "cancel")
            return (
              <CancelCell
                cancelled={row.cancelled}
                disabled={disabled}
                onCancel={() => {
                  cancel(row)
                }}
                onUndo={() => {
                  undo(row)
                }}
              />
            )
          if (column.key === "change")
            return (
              <ChangeCell
                currency={conversionCurrency(args, row)}
                disabled={disabled}
                onChange={edit(row)}
                row={row}
              />
            )
          return null
        }}
        rowClassName={(dataRow) =>
          byId.get(String(dataRow["id"]))?.cancelled ? "opacity-60" : undefined
        }
        rowDetails={false}
        rowNoun={["change", "changes"]}
        rows={rows.map((row) => ({
          cancel: "",
          change: conversionValueText(row.setting, row.value, conversionCurrency(args, row)),
          conversions:
            row.conversions === null
              ? "—"
              : row.conversions.toLocaleString("en-GB", { maximumFractionDigits: 1 }),
          id: row.id,
          name: row.name,
          setting: CONVERSION_SETTING_TITLES[row.setting],
        }))}
        {...(tools
          ? {
              searchable: true,
              tabs: [
                { id: "all", label: "All", match: () => true },
                {
                  hideWhenEmpty: true,
                  id: "attention",
                  label: "Needs Attention",
                  match: (dataRow) => {
                    const row = byId.get(String(dataRow["id"]))
                    return row !== undefined && !row.cancelled && row.problem !== null
                  },
                },
              ],
            }
          : {})}
      />
      <AddChange
        noun="Conversion Action"
        titles={CONVERSION_SETTING_TITLES}
        targets={args.items
          .filter((item) => item.kind === "action")
          .map((item) => ({
            key: item.key,
            name: rows.find((row) => row.key === item.key)?.name ?? item.label,
            options: addableConversionSettings(checked, rows, item.key),
          }))}
        disabled={disabled}
        onAdd={(key, setting, value) => {
          save(addedConversionSetting(args, key, setting, value), cancelled)
        }}
      />
      {changesBidding(rows) ? (
        <p className="text-muted-foreground flex items-start gap-2 text-sm">
          <InfoIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          <span>
            Smart Bidding chases primary conversions in goals that count for bidding, at their
            values. Every campaign that uses account goals follows these changes.
          </span>
        </p>
      ) : null}
      {conversionsNeedCheck(args, checked) && args.items.length > 0 ? (
        <CheckChanges
          canCheck
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

function NameCell({ row }: { row: ConversionRow }) {
  return (
    <div className="grid min-w-0 gap-0.5 text-sm">
      <span className="font-medium wrap-anywhere whitespace-normal">{row.name}</span>
      {row.kind === "goal" ? (
        <span className="text-muted-foreground text-xs">Account goal</span>
      ) : null}
      {!row.cancelled && row.problem ? (
        <span className="text-destructive text-xs wrap-anywhere whitespace-normal">
          {row.problem}
        </span>
      ) : null}
    </div>
  )
}

/** The live value, then the new one as an inline edit. */
function ChangeCell({
  currency,
  disabled,
  onChange,
  row,
}: {
  currency: string | null
  disabled: boolean
  onChange: Edit
  row: ConversionRow
}) {
  const was = conversionValueText(row.setting, row.was, currency)
  if (row.cancelled)
    return (
      <span className="text-muted-foreground pt-1 text-sm line-through">
        {was} → {conversionValueText(row.setting, row.value, currency)}
      </span>
    )
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2 text-sm">
      <span className="text-muted-foreground wrap-anywhere whitespace-normal">{was} →</span>
      <SettingEditor
        disabled={disabled}
        label={`New ${CONVERSION_SETTING_TITLES[row.setting].toLowerCase()} for ${row.name}`}
        onChange={onChange}
        row={row}
      />
      {row.unchanged ? <Badge variant="secondary">Already Set</Badge> : null}
    </div>
  )
}

function SettingEditor({
  disabled,
  label,
  onChange,
  row,
}: {
  disabled: boolean
  label: string
  onChange: Edit
  row: ConversionRow
}): ReactNode {
  const { setting, value } = row
  const choices = CHOICES[setting]
  if (choices)
    return (
      <SegmentedChoice
        ariaLabel={label}
        compact
        disabled={disabled}
        onChange={(next) => {
          onChange(typeof value === "boolean" ? next === "true" : next)
        }}
        options={choices}
        value={String(value)}
      />
    )
  if (setting === "click_through_days" || setting === "view_through_days") {
    const [low, high] = WINDOW_DAYS[setting]
    return (
      <span className="flex items-center gap-1.5">
        <CommittedInput
          ariaLabel={label}
          className="h-7 w-20 text-sm tabular-nums"
          disabled={disabled}
          onCommit={(next) => {
            const days = Number(next.trim())
            if (Number.isInteger(days) && days >= low && days <= high) onChange(days)
          }}
          value={typeof value === "number" ? String(value) : ""}
        />
        <span className="text-muted-foreground">days</span>
      </span>
    )
  }
  return (
    <CommittedInput
      ariaLabel={label}
      className={
        setting === "currency" ? "h-7 w-20 text-sm uppercase" : "h-7 w-32 text-sm tabular-nums"
      }
      disabled={disabled}
      onCommit={(next) => {
        const trimmed = next.trim()
        if (setting === "currency") {
          if (/^[a-z]{3}$/i.test(trimmed)) onChange(trimmed.toUpperCase())
        } else if (/^\d{1,12}(\.\d{1,6})?$/.test(trimmed)) onChange(String(Number(trimmed)))
      }}
      value={typeof value === "string" ? value : ""}
    />
  )
}
