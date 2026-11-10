// apps/web/src/integrations/google_ads/components/update-ad-groups-approval.tsx

import { XIcon } from "lucide-react"
import { useMemo, useState, type ReactNode } from "react"

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
import { ChangeBanner } from "@/integrations/ads/components/change-banner"
import { ChangeSummary, type ChangeSummaryLine } from "@/integrations/ads/components/change-summary"
import { CommittedInput } from "@/integrations/ads/components/committed-input"
import { SegmentedChoice } from "@/integrations/ads/components/controls"
import { AddChange } from "@/integrations/google_ads/components/add-change"
import { CheckChanges } from "@/integrations/google_ads/components/check-changes"
import {
  canonicalMoney,
  moneyInput,
  roasPercent,
} from "@/integrations/google_ads/lib/campaign-bidding"
import {
  AD_GROUP_SETTING_TITLES,
  AD_GROUP_SETTINGS,
  addableSettings,
  addedAdGroupChanges,
  adGroupCounts,
  adGroupCurrency,
  adGroupRows,
  adGroupsBannerDetail,
  adGroupsNeedCheck,
  adGroupValueText,
  editedAdGroupChanges,
  parseCancelledAdGroupSettings,
  restoredAdGroupChanges,
  ROTATION_LABELS,
  ROTATIONS,
  scaledMoney,
  type AdGroupRow,
  type AdGroupSetting,
  type AdGroupValue,
  type CancelledAdGroupSetting,
  type UpdateAdGroupsArgs,
} from "@/integrations/google_ads/lib/update-ad-groups"
import { parametersText, parseParametersText } from "@/integrations/google_ads/lib/update-campaigns"
import { currencySymbol } from "@/lib/format"
import { cn } from "@/lib/utils"

// Below this many changes the summary and the table tools only add noise.
const TOOLS_FROM = 10

const COLUMNS: DataColumn[] = [
  { key: "ad_group", kind: "text", label: "Ad Group", width: 220 },
  { key: "campaign", kind: "text", label: "Campaign", width: 200 },
  { key: "setting", kind: "text", label: "Setting", width: 140 },
  { key: "change", kind: "text", label: "Change", width: 300 },
  { key: "cancel", kind: "text", label: "Cancel", width: 80 },
]

const ROTATION_OPTIONS = ROTATIONS.map((value) => ({ value, label: ROTATION_LABELS[value] }))

type Edit = (value: AdGroupValue) => void

export function UpdateAdGroupsApproval({
  args,
  checked,
  controls,
  disabled,
  onFieldEdit,
}: {
  args: UpdateAdGroupsArgs
  // The request Google last answered for.
  checked: UpdateAdGroupsArgs
  controls: ToolApprovalDecisionControls
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
}) {
  const [tab, setTab] = useState("all")
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set())
  const cancelled = useMemo(
    () => parseCancelledAdGroupSettings(controls.retained),
    [controls.retained]
  )
  const rows = useMemo(() => adGroupRows(args, checked, cancelled), [args, checked, cancelled])
  const byId = useMemo(() => new Map(rows.map((row) => [row.id, row])), [rows])
  const counts = adGroupCounts(rows)
  const many = new Set(rows.map((row) => row.key)).size > 1
  const tools = rows.length >= TOOLS_FROM
  const accountIds = [...new Set(rows.filter((row) => !row.cancelled).map((row) => row.customerId))]

  // A review redraws the card, so cancelled settings live beside the request for Undo.
  const save = (
    changes: Record<string, unknown>[],
    nextCancelled: readonly CancelledAdGroupSetting[]
  ) => {
    if (nextCancelled !== cancelled) controls.onRetain?.(nextCancelled)
    onFieldEdit("changes", changes)
  }
  const setValues = (
    ids: Iterable<string>,
    value: (row: { key: string; setting: AdGroupSetting }) => AdGroupValue
  ) => {
    save(editedAdGroupChanges(args, new Set(ids), value), cancelled)
  }
  const cancel = (ids: Iterable<string>) => {
    const chosen = new Set(ids)
    const items = rows.flatMap((row) => {
      const adGroup = row.change?.entry["ad_group"]
      return chosen.has(row.id) && !row.cancelled && adGroup && typeof adGroup === "object"
        ? [
            {
              adGroup: adGroup as Record<string, unknown>,
              key: row.key,
              setting: row.setting,
              value: row.value,
            },
          ]
        : []
    })
    save(
      editedAdGroupChanges(args, chosen, () => undefined),
      [...cancelled, ...items]
    )
  }
  const undo = (id: string) => {
    const item = cancelled.find((entry) => `${entry.key}|${entry.setting}` === id)
    if (item)
      save(
        restoredAdGroupChanges(args, [item]),
        cancelled.filter((entry) => entry !== item)
      )
  }
  const liveOf = (match: (row: AdGroupRow) => boolean) =>
    rows.filter((row) => !row.cancelled && match(row))
  const cancelCell = (row: AdGroupRow) => (
    <CancelCell
      disabled={disabled}
      onCancel={() => {
        cancel([row.id])
      }}
      onUndo={() => {
        undo(row.id)
      }}
      row={row}
    />
  )
  const edit =
    (row: AdGroupRow): Edit =>
    (value) => {
      setValues([row.id], () => value)
    }

  return (
    <div className="grid min-w-0 gap-3">
      <ChangeBanner
        aside={
          <p className="text-sm font-medium tabular-nums">
            {String(counts.apply)} {counts.apply === 1 ? "change" : "changes"}
          </p>
        }
        detail={adGroupsBannerDetail(counts, accountIds, args.accounts)}
      />
      {tools ? (
        <>
          <ChangeSummary
            lines={[
              ...AD_GROUP_SETTINGS.map((setting): ChangeSummaryLine => {
                const lineRows = liveOf((row) => row.setting === setting)
                return {
                  action: (
                    <EveryAction
                      args={args}
                      disabled={disabled}
                      rows={lineRows}
                      setting={setting}
                      setValues={setValues}
                    />
                  ),
                  count: lineRows.length,
                  id: setting,
                  label: AD_GROUP_SETTING_TITLES[setting],
                  onSelect: () => {
                    setTab(setting)
                  },
                  selected: tab === setting,
                }
              }),
              {
                action: (
                  <Button
                    disabled={disabled}
                    onClick={() => {
                      cancel(liveOf((row) => row.problem !== null).map((row) => row.id))
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
          <AttentionLine
            count={counts.problems}
            onShow={() => {
              setTab("attention")
            }}
          />
        </>
      ) : null}
      {many ? (
        <DataTable
          activeTab={tab}
          columns={COLUMNS}
          exportFilename="google-ads-ad-group-changes.csv"
          onTabChange={setTab}
          pageSize={25}
          renderCell={(column, dataRow) => {
            const row = byId.get(String(dataRow["id"]))
            if (!row) return null
            if (column.key === "ad_group") return <NameCell row={row} />
            if (column.key === "campaign") return <CampaignCell row={row} />
            if (column.key === "cancel") return cancelCell(row)
            if (column.key === "change")
              return (
                <ChangeCell
                  currency={adGroupCurrency(args, row)}
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
            ad_group: row.adGroupName,
            campaign: row.campaignName ?? "",
            cancel: "",
            change: adGroupValueText(row.setting, row.value, adGroupCurrency(args, row)),
            id: row.id,
            setting: AD_GROUP_SETTING_TITLES[row.setting],
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
                tabs: settingTabs(byId),
              }
            : {})}
        />
      ) : (
        <SoleAdGroup
          args={args}
          cancelCell={cancelCell}
          disabled={disabled}
          edit={edit}
          rows={rows}
        />
      )}
      <AddChange
        noun="Ad Group"
        titles={AD_GROUP_SETTING_TITLES}
        targets={args.changes.map((change) => ({
          key: change.key,
          name: rows.find((row) => row.key === change.key)?.adGroupName ?? change.label,
          options: addableSettings(checked, rows, change.key),
        }))}
        disabled={disabled}
        onAdd={(key, setting, value) => {
          save(addedAdGroupChanges(args, key, setting, value), cancelled)
        }}
      />
      {adGroupsNeedCheck(args, checked) && args.changes.length > 0 ? (
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

/** One ad group: its campaign's bidding, then each setting on one line. */
function SoleAdGroup({
  args,
  cancelCell,
  disabled,
  edit,
  rows,
}: {
  args: UpdateAdGroupsArgs
  cancelCell: (row: AdGroupRow) => ReactNode
  disabled: boolean
  edit: (row: AdGroupRow) => Edit
  rows: readonly AdGroupRow[]
}) {
  const [first] = rows
  if (!first) return null
  return (
    <section aria-label={first.adGroupName} className="overflow-hidden rounded-lg border">
      {first.campaignName ? (
        <p className="text-muted-foreground border-b px-3 py-2 text-sm">
          In <span className="text-foreground font-medium">{first.campaignName}</span>
          {first.strategyName ? `, which uses ${first.strategyName}` : ""}.
        </p>
      ) : null}
      <ul className="divide-y">
        {rows.map((row) => (
          <li
            key={row.id}
            className="grid grid-cols-[9rem_minmax(0,1fr)_auto] items-start gap-3 px-3 py-2"
          >
            <div className="grid min-w-0 gap-0.5 pt-1 text-sm">
              <span className="font-medium">{AD_GROUP_SETTING_TITLES[row.setting]}</span>
              <Problem row={row} />
            </div>
            <ChangeCell
              currency={adGroupCurrency(args, row)}
              disabled={disabled}
              onChange={edit(row)}
              row={row}
            />
            {cancelCell(row)}
          </li>
        ))}
      </ul>
    </section>
  )
}

function isBid(setting: AdGroupSetting): boolean {
  return setting === "cpc_bid" || setting === "target_cpa" || setting === "target_roas"
}

function settingTabs(byId: ReadonlyMap<string, AdGroupRow>): DataTableTab[] {
  const live = (dataRow: DataRow, match: (row: AdGroupRow) => boolean) => {
    const row = byId.get(String(dataRow["id"]))
    return row !== undefined && !row.cancelled && match(row)
  }
  return [
    { id: "all", label: "All", match: () => true },
    ...AD_GROUP_SETTINGS.map((setting) => ({
      hideWhenEmpty: true,
      id: setting,
      label: AD_GROUP_SETTING_TITLES[setting],
      match: (dataRow: DataRow) => live(dataRow, (row) => row.setting === setting),
    })),
    {
      hideWhenEmpty: true,
      id: "attention",
      label: "Needs Attention",
      match: (dataRow) => live(dataRow, (row) => row.problem !== null),
    },
  ]
}

function Problem({ row }: { row: AdGroupRow }) {
  return !row.cancelled && row.problem ? (
    <span className="text-destructive text-xs wrap-anywhere whitespace-normal">{row.problem}</span>
  ) : null
}

function NameCell({ row }: { row: AdGroupRow }) {
  return (
    <div className="grid min-w-0 gap-0.5 text-sm">
      <span className="font-medium wrap-anywhere whitespace-normal">{row.adGroupName}</span>
      <Problem row={row} />
    </div>
  )
}

/** The campaign, with the strategy that decides which ad group bids Google uses. */
function CampaignCell({ row }: { row: AdGroupRow }) {
  return (
    <div className="grid min-w-0 gap-0.5 text-sm">
      <span className="wrap-anywhere whitespace-normal">{row.campaignName ?? "—"}</span>
      {row.strategyName ? (
        <span className="text-muted-foreground text-xs">{row.strategyName}</span>
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
  row: AdGroupRow
}) {
  const was = adGroupValueText(row.setting, row.was, currency)
  if (row.cancelled)
    return (
      <span className="text-muted-foreground pt-1 text-sm line-through">
        {was} → {adGroupValueText(row.setting, row.value, currency)}
      </span>
    )
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2 text-sm">
      <span className="text-muted-foreground wrap-anywhere whitespace-normal">{was} →</span>
      <SettingEditor
        currency={currency}
        disabled={disabled}
        label={`New ${AD_GROUP_SETTING_TITLES[row.setting].toLowerCase()} for ${row.adGroupName}`}
        onChange={onChange}
        row={row}
      />
      {row.unchanged ? <Badge variant="secondary">Already Set</Badge> : null}
    </div>
  )
}

function SettingEditor({
  currency,
  disabled,
  label,
  onChange,
  row,
}: {
  currency: string | null
  disabled: boolean
  label: string
  onChange: Edit
  row: AdGroupRow
}): ReactNode {
  const { setting, value } = row
  if (setting === "ad_rotation")
    return (
      <SegmentedChoice
        ariaLabel={label}
        compact
        disabled={disabled}
        onChange={onChange}
        options={ROTATION_OPTIONS}
        value={ROTATIONS.find((item) => item === value) ?? null}
      />
    )
  if (Array.isArray(value))
    return (
      <CommittedInput
        ariaLabel={label}
        className="h-7 min-w-48 flex-1 text-sm"
        disabled={disabled}
        onCommit={(next) => {
          const parsed = parseParametersText(next)
          if (parsed) onChange(parsed)
        }}
        placeholder="key=value, key=value"
        value={parametersText(value)}
      />
    )
  if (isBid(setting)) {
    const roas = setting === "target_roas"
    const symbol = !roas && currency ? currencySymbol(currency) : null
    return (
      <div className="relative flex items-center">
        {symbol ? (
          <span
            aria-hidden="true"
            className="text-muted-foreground pointer-events-none absolute left-2 text-sm"
          >
            {symbol}
          </span>
        ) : null}
        <CommittedInput
          ariaLabel={label}
          className={cn("h-7 w-32 text-sm tabular-nums", symbol && "pl-6", roas && "pr-6")}
          disabled={disabled}
          onCommit={(next) => {
            const trimmed = next.trim()
            const number = Number(trimmed)
            // An empty target follows the campaign; Google always keeps a default CPC bid.
            if (!trimmed) {
              if (setting !== "cpc_bid") onChange(null)
            } else if (Number.isFinite(number) && number > 0)
              onChange(roas ? number / 100 : canonicalMoney(trimmed))
          }}
          placeholder={setting === "cpc_bid" ? "Amount" : "Campaign's target"}
          value={
            typeof value === "number"
              ? roasPercent(value)
              : typeof value === "string"
                ? moneyInput(value)
                : ""
          }
        />
        {roas ? (
          <span
            aria-hidden="true"
            className="text-muted-foreground pointer-events-none absolute right-2 text-sm"
          >
            %
          </span>
        ) : null}
      </div>
    )
  }
  return (
    <CommittedInput
      ariaLabel={label}
      className="h-7 min-w-48 flex-1 text-sm"
      disabled={disabled}
      onCommit={(next) => {
        const trimmed = next.trim()
        if (trimmed || setting !== "name") onChange(trimmed || null)
      }}
      {...(setting === "name" ? {} : { placeholder: "None" })}
      value={typeof value === "string" ? value : ""}
    />
  )
}

/** One control that edits every ad group in a summary line, where that makes sense. */
function EveryAction({
  args,
  disabled,
  rows,
  setting,
  setValues,
}: {
  args: UpdateAdGroupsArgs
  disabled: boolean
  rows: readonly AdGroupRow[]
  setting: AdGroupSetting
  setValues: (
    ids: Iterable<string>,
    value: (row: { key: string; setting: AdGroupSetting }) => AdGroupValue
  ) => void
}): ReactNode {
  const [first] = rows
  if (!first || rows.length < 2) return null
  const ids = rows.map((row) => row.id)
  if (setting === "ad_rotation")
    return (
      <SegmentedChoice
        ariaLabel="Ad rotation for every ad group in this line"
        compact
        disabled={disabled}
        onChange={(value) => {
          setValues(ids, () => value)
        }}
        options={ROTATION_OPTIONS}
        value={
          rows.every((row) => row.value === first.value)
            ? (ROTATIONS.find((item) => item === first.value) ?? null)
            : null
        }
      />
    )
  if (setting !== "cpc_bid" && setting !== "target_cpa") return null
  // Each new amount is the live one changed by the same percentage.
  const byKey = new Map(rows.map((row) => [row.key, row]))
  return (
    <CommittedInput
      ariaLabel={`Change every ${AD_GROUP_SETTING_TITLES[setting].toLowerCase()} in this line by a percentage`}
      className="h-7 w-28 text-sm tabular-nums"
      disabled={disabled}
      onCommit={(next) => {
        const percent = Number(next.trim().replace(/%$/, ""))
        if (!next.trim() || !Number.isFinite(percent) || percent <= -100) return
        setValues(ids, ({ key }) => {
          const row = byKey.get(key)
          const was = typeof row?.was === "string" ? row.was : null
          return was && row
            ? scaledMoney(was, percent, adGroupCurrency(args, row))
            : (row?.value ?? null)
        })
      }}
      placeholder="Change by %"
      value=""
    />
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
  row: AdGroupRow
}) {
  return row.cancelled ? (
    <Button disabled={disabled} onClick={onUndo} size="sm" type="button" variant="ghost">
      Undo
    </Button>
  ) : (
    <Button
      aria-label="Cancel This Change"
      disabled={disabled}
      onClick={onCancel}
      size="icon-xs"
      title="Cancel This Change"
      type="button"
      variant="ghost"
    >
      <XIcon />
    </Button>
  )
}
