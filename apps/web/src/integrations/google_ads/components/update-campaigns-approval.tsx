// apps/web/src/integrations/google_ads/components/update-campaigns-approval.tsx

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
import { BiddingCell, BiddingChange } from "@/integrations/google_ads/components/bidding-editor"
import { CheckChanges } from "@/integrations/google_ads/components/check-changes"
import {
  canonicalMoney,
  roasPercent,
  TARGETS,
  type Bidding,
  type BiddingContext,
} from "@/integrations/google_ads/lib/campaign-bidding"
import {
  CAMPAIGN_SETTINGS,
  campaignCounts,
  campaignRows,
  campaignsBannerDetail,
  campaignsBannerTitle,
  canCheckCampaigns,
  editedChanges,
  isBidding,
  needsCheck,
  parametersText,
  parseCancelled,
  parseParametersText,
  restoredChanges,
  rowContext,
  sameValue,
  SETTING_TITLES,
  valueText,
  type CampaignRow,
  type CampaignSetting,
  type CancelledSetting,
  type SettingValue,
  type UpdateCampaignsArgs,
} from "@/integrations/google_ads/lib/update-campaigns"

// Below this many changes the summary and the table tools only add noise.
const TOOLS_FROM = 10

const COLUMNS: DataColumn[] = [
  { key: "campaign", kind: "text", label: "Campaign", width: 220 },
  { key: "setting", kind: "text", label: "Setting", width: 150 },
  { key: "change", kind: "text", label: "Change", width: 420 },
  { key: "cancel", kind: "text", label: "Cancel", width: 80 },
]

const ON_OFF = [
  { value: "on", label: "On" },
  { value: "off", label: "Off" },
] as const

export function UpdateCampaignsApproval({
  args,
  checked,
  controls,
  disabled,
  onFieldEdit,
}: {
  args: UpdateCampaignsArgs
  // The request Google last answered for.
  checked: UpdateCampaignsArgs
  controls: ToolApprovalDecisionControls
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
}) {
  const [tab, setTab] = useState("all")
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set())
  const cancelled = useMemo(() => parseCancelled(controls.retained), [controls.retained])
  const rows = useMemo(() => campaignRows(args, checked, cancelled), [args, checked, cancelled])
  const byId = useMemo(() => new Map(rows.map((row) => [row.id, row])), [rows])
  const counts = campaignCounts(rows)
  const many = new Set(rows.map((row) => row.key)).size > 1
  const tools = rows.length >= TOOLS_FROM
  const accountIds = [...new Set(rows.filter((row) => !row.cancelled).map((row) => row.customerId))]

  // A review redraws the card, so cancelled settings live beside the request for Undo.
  const save = (changes: Record<string, unknown>[], nextCancelled: readonly CancelledSetting[]) => {
    if (nextCancelled !== cancelled) controls.onRetain?.(nextCancelled)
    onFieldEdit("changes", changes)
  }
  const setValue = (ids: Iterable<string>, value: SettingValue) => {
    save(
      editedChanges(args, new Set(ids), () => value),
      cancelled
    )
  }
  const cancel = (ids: Iterable<string>) => {
    const chosen = new Set(ids)
    const items = rows.flatMap((row) => {
      const campaign = row.change?.entry["campaign"]
      return chosen.has(row.id) && !row.cancelled && campaign && typeof campaign === "object"
        ? [
            {
              campaign: campaign as Record<string, unknown>,
              key: row.key,
              setting: row.setting,
              value: row.value,
            },
          ]
        : []
    })
    save(
      editedChanges(args, chosen, () => undefined),
      [...cancelled, ...items]
    )
  }
  const undo = (id: string) => {
    const item = cancelled.find((entry) => `${entry.key}|${entry.setting}` === id)
    if (item)
      save(
        restoredChanges(args, [item]),
        cancelled.filter((entry) => entry !== item)
      )
  }
  // One campaign shows bidding in its own section, beside the list of its other settings.
  const listed = rows.filter((row) => row.setting !== "bidding")
  const idsOf = (match: (row: CampaignRow) => boolean) =>
    rows.filter((row) => !row.cancelled && match(row)).map((row) => row.id)

  const cells = (row: CampaignRow) => ({
    cancel: (
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
    ),
    change: (
      <ChangeCell
        context={rowContext(args, row)}
        disabled={disabled}
        onChange={(value) => {
          setValue([row.id], value)
        }}
        row={row}
      />
    ),
  })

  return (
    <div className="grid min-w-0 gap-3">
      <ChangeBanner
        aside={
          <p className="text-sm font-medium tabular-nums">
            {String(counts.apply)} {counts.apply === 1 ? "change" : "changes"}
          </p>
        }
        detail={campaignsBannerDetail(counts, accountIds, args.accounts).map((line) => (
          <p key={line}>{line}</p>
        ))}
        title={campaignsBannerTitle(counts)}
      />
      {tools ? (
        <>
          <ChangeSummary
            lines={[
              ...CAMPAIGN_SETTINGS.map((setting): ChangeSummaryLine => ({
                action: (
                  <EveryAction
                    disabled={disabled}
                    onChange={(value) => {
                      setValue(
                        idsOf((row) => row.setting === setting),
                        value
                      )
                    }}
                    rows={rows.filter((row) => !row.cancelled && row.setting === setting)}
                    setting={setting}
                  />
                ),
                count: rows.filter((row) => !row.cancelled && row.setting === setting).length,
                id: setting,
                label: SETTING_TITLES[setting],
                onSelect: () => {
                  setTab(setting)
                },
                selected: tab === setting,
              })),
              {
                action: (
                  <Button
                    disabled={disabled}
                    onClick={() => {
                      cancel(idsOf((row) => row.problem !== null))
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
          exportFilename="google-ads-campaign-changes.csv"
          onTabChange={setTab}
          pageSize={25}
          renderCell={(column, dataRow) => {
            const row = byId.get(String(dataRow["id"]))
            if (!row) return null
            if (column.key === "campaign") return <CampaignCell row={row} />
            if (column.key === "change" || column.key === "cancel") return cells(row)[column.key]
            return null
          }}
          rowClassName={(dataRow) =>
            byId.get(String(dataRow["id"]))?.cancelled ? "opacity-60" : undefined
          }
          rowDetails={false}
          rowNoun={["change", "changes"]}
          rows={rows.map((row) => ({
            campaign: row.campaignName,
            cancel: "",
            change: valueText(row.setting, row.value, rowContext(args, row)),
            id: row.id,
            setting: SETTING_TITLES[row.setting],
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
        <>
          {listed.length > 0 ? (
            <ul
              aria-label={rows[0]?.campaignName ?? "Campaign"}
              className="divide-y overflow-hidden rounded-lg border"
            >
              {listed.map((row) => {
                const { cancel: cancelCell, change } = cells(row)
                return (
                  <li
                    key={row.id}
                    className="grid grid-cols-[9rem_minmax(0,1fr)_auto] items-start gap-3 px-3 py-2"
                  >
                    <SettingCell row={row} />
                    {change}
                    {cancelCell}
                  </li>
                )
              })}
            </ul>
          ) : null}
          {rows
            .filter((row) => row.setting === "bidding")
            .map((row) => (
              <BiddingChange
                key={row.id}
                context={rowContext(args, row)}
                disabled={disabled}
                onCancel={() => {
                  cancel([row.id])
                }}
                onChange={(value) => {
                  setValue([row.id], value)
                }}
                onUndo={() => {
                  undo(row.id)
                }}
                row={row}
              />
            ))}
        </>
      )}
      {needsCheck(args, checked) && args.changes.length > 0 ? (
        <CheckChanges
          canCheck={canCheckCampaigns(args)}
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

function settingTabs(byId: ReadonlyMap<string, CampaignRow>): DataTableTab[] {
  const live = (dataRow: DataRow, match: (row: CampaignRow) => boolean) => {
    const row = byId.get(String(dataRow["id"]))
    return row !== undefined && !row.cancelled && match(row)
  }
  return [
    { id: "all", label: "All", match: () => true },
    ...CAMPAIGN_SETTINGS.map((setting) => ({
      hideWhenEmpty: true,
      id: setting,
      label: SETTING_TITLES[setting],
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

function Problem({ row }: { row: CampaignRow }) {
  return !row.cancelled && row.problem ? (
    <span className="text-destructive text-xs wrap-anywhere whitespace-normal">{row.problem}</span>
  ) : null
}

function CampaignCell({ row }: { row: CampaignRow }) {
  return (
    <div className="grid min-w-0 gap-0.5 text-sm">
      <span className="font-medium wrap-anywhere whitespace-normal">{row.campaignName}</span>
      <Problem row={row} />
    </div>
  )
}

function SettingCell({ row }: { row: CampaignRow }) {
  return (
    <div className="grid min-w-0 gap-0.5 pt-1 text-sm">
      <span className="font-medium">{SETTING_TITLES[row.setting]}</span>
      <Problem row={row} />
    </div>
  )
}

/** The live value, then the new one as an inline edit. */
function ChangeCell({
  context,
  disabled,
  onChange,
  row,
}: {
  context: BiddingContext
  disabled: boolean
  onChange: (value: SettingValue) => void
  row: CampaignRow
}) {
  if (isBidding(row.value))
    return <BiddingCell context={context} disabled={disabled} onChange={onChange} row={row} />
  if (row.cancelled)
    return (
      <span className="text-muted-foreground pt-1 text-sm line-through">
        {valueText(row.setting, row.was, context)} → {valueText(row.setting, row.value, context)}
      </span>
    )
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2 text-sm">
      <span className="text-muted-foreground wrap-anywhere whitespace-normal">
        {valueText(row.setting, row.was, context)} →
      </span>
      <SettingEditor
        disabled={disabled}
        label={`New ${SETTING_TITLES[row.setting].toLowerCase()} for ${row.campaignName}`}
        onChange={onChange}
        setting={row.setting}
        value={row.value}
      />
      {row.unchanged ? <Badge variant="secondary">Already Set</Badge> : null}
    </div>
  )
}

function SettingEditor({
  disabled,
  label,
  onChange,
  setting,
  value,
}: {
  disabled: boolean
  label: string
  onChange: (value: SettingValue) => void
  setting: CampaignSetting
  value: Exclude<SettingValue, Bidding>
}): ReactNode {
  if (typeof value === "boolean")
    return (
      <SegmentedChoice
        ariaLabel={label}
        compact
        disabled={disabled}
        onChange={(next) => {
          onChange(next === "on")
        }}
        options={ON_OFF}
        value={value ? "on" : "off"}
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
  if (setting === "start_date" || setting === "end_date")
    return (
      <>
        <CommittedInput
          ariaLabel={label}
          className="h-7 w-40 text-sm"
          disabled={disabled}
          onCommit={(next) => {
            // An empty end date runs the campaign with no end; a start date is always required.
            if (next || setting === "end_date") onChange(next || null)
          }}
          type="date"
          value={value ?? ""}
        />
        {value === null ? <span className="text-muted-foreground">No end date</span> : null}
      </>
    )
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
      value={value ?? ""}
    />
  )
}

/** One control that sets the setting on every campaign in a summary line, where that makes sense. */
function EveryAction({
  disabled,
  onChange,
  rows,
  setting,
}: {
  disabled: boolean
  onChange: (value: SettingValue) => void
  rows: readonly CampaignRow[]
  setting: CampaignSetting
}): ReactNode {
  const [first] = rows
  if (!first || rows.length < 2) return null
  const shared = rows.every((row) => sameValue(row.value, first.value))
  if (setting === "search_partners" || setting === "display_expansion")
    return (
      <SegmentedChoice
        ariaLabel={`${SETTING_TITLES[setting]} for every campaign in this line`}
        compact
        disabled={disabled}
        onChange={(next) => {
          onChange(next === "on")
        }}
        options={ON_OFF}
        value={shared ? (first.value ? "on" : "off") : null}
      />
    )
  if (setting === "bidding")
    return <EveryTarget disabled={disabled} onChange={onChange} rows={rows} />
  if (setting === "end_date")
    return (
      <CommittedInput
        ariaLabel="End date for every campaign in this line"
        className="h-7 w-40 text-sm"
        disabled={disabled}
        onCommit={(next) => {
          onChange(next || null)
        }}
        type="date"
        value={shared && typeof first.value === "string" ? first.value : ""}
      />
    )
  return null
}

// The one target each strategy takes, so a summary line can set it on every campaign.
const LINE_TARGETS = {
  MAXIMIZE_CLICKS: "max_cpc",
  MAXIMIZE_CONVERSIONS: "target_cpa",
  MAXIMIZE_CONVERSION_VALUE: "target_roas",
} as const

/** Sets one target on every bidding change in the line, when they share a strategy and target. */
function EveryTarget({
  disabled,
  onChange,
  rows,
}: {
  disabled: boolean
  onChange: (value: SettingValue) => void
  rows: readonly CampaignRow[]
}): ReactNode {
  const values = rows.map((row) => row.value).filter(isBidding)
  const [first] = values
  if (!first || values.length !== rows.length) return null
  const strategy = first.strategy
  const keys =
    strategy === TARGETS
      ? (["target_cpa", "target_roas", "max_cpc"] as const).filter((key) => first[key] != null)
      : strategy in LINE_TARGETS
        ? [LINE_TARGETS[strategy as keyof typeof LINE_TARGETS]]
        : []
  const [key] = keys
  if (keys.length !== 1 || !key || values.some((value) => value.strategy !== strategy)) return null
  const shared = values.every((value) => value[key] === first[key]) ? first[key] : null
  const roas = key === "target_roas"
  return (
    <CommittedInput
      ariaLabel={`${roas ? "Target ROAS (%)" : key === "target_cpa" ? "Target CPA" : "Maximum click bid"} for every campaign in this line`}
      className="h-7 w-28 text-sm tabular-nums"
      disabled={disabled}
      onCommit={(next) => {
        const trimmed = next.trim()
        const number = Number(trimmed)
        if (!trimmed || !Number.isFinite(number) || number <= 0) return
        onChange({ ...first, [key]: roas ? number / 100 : canonicalMoney(trimmed) })
      }}
      placeholder={roas ? "ROAS %" : "Amount"}
      value={shared == null ? "" : typeof shared === "number" ? roasPercent(shared) : shared}
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
  row: CampaignRow
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
