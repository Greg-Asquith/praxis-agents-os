// apps/web/src/integrations/google_ads/components/update-keywords-approval.tsx

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
import { ParentTable, type ParentRow } from "@/integrations/ads/components/parent-table"
import type { KeywordMatchType } from "@/integrations/ads/lib/keyword-notation"
import { AddChange } from "@/integrations/google_ads/components/add-change"
import { CheckChanges } from "@/integrations/google_ads/components/check-changes"
import { canonicalMoney, moneyInput } from "@/integrations/google_ads/lib/campaign-bidding"
import { MATCH_TYPE_LABELS, MATCH_TYPES } from "@/integrations/google_ads/lib/negative-keywords"
import { scaledMoney } from "@/integrations/google_ads/lib/update-ad-groups"
import { parametersText, parseParametersText } from "@/integrations/google_ads/lib/update-campaigns"
import {
  KEYWORD_SETTING_TITLES,
  KEYWORD_SETTINGS,
  addableSettings,
  addedKeywordChanges,
  editedKeywordChanges,
  keywordCounts,
  keywordAdGroup,
  keywordCurrency,
  keywordRows,
  keywordsBannerDetail,
  keywordsNeedCheck,
  keywordValueText,
  parseCancelledKeywordSettings,
  parseUrls,
  replacesKeyword,
  restoredKeywordChanges,
  type CancelledKeywordSetting,
  type KeywordRow,
  type KeywordSetting,
  type KeywordValue,
  type UpdateKeywordsArgs,
} from "@/integrations/google_ads/lib/update-keywords"
import { currencySymbol } from "@/lib/format"
import { cn } from "@/lib/utils"

// Below this many changes the summary and the table tools only add noise.
const TOOLS_FROM = 10

const COLUMNS: DataColumn[] = [
  { key: "keyword", kind: "text", label: "Keyword", width: 220 },
  // The ad groups table above names them, so this column is for the chooser and the export.
  { key: "ad_group", kind: "text", label: "Ad Group", width: 200, hidden: true },
  { key: "setting", kind: "text", label: "Setting", width: 130 },
  { key: "change", kind: "text", label: "Change", width: 300 },
  { key: "cancel", kind: "text", label: "Cancel", width: 80 },
]

const PARENT_COLUMNS: DataColumn[] = [
  { key: "keywords", kind: "number", label: "Keywords", width: 100 },
  { key: "changes", kind: "number", label: "Changes", width: 100 },
]

/** One row per ad group the changes are in, in the order its keywords first appear. */
function adGroupParents(rows: readonly KeywordRow[]): ParentRow[] {
  const groups = new Map<string, KeywordRow[]>()
  for (const row of rows) {
    const key = keywordAdGroup(row)
    groups.set(key, [...(groups.get(key) ?? []), row])
  }
  return [...groups].map(([key, items]) => {
    const live = items.filter((row) => !row.cancelled)
    const first = items.find((row) => row.adGroupName) ?? items[0]
    return {
      cancelled: live.length === 0,
      context: first?.campaignName ?? null,
      key,
      name: first?.adGroupName ?? `Ad group ${key.split("/").pop() ?? ""}`,
      problems: live.filter((row) => row.problem !== null).length,
      values: { changes: live.length, keywords: new Set(live.map((row) => row.key)).size },
    }
  })
}

const MATCH_OPTIONS = MATCH_TYPES.map((value) => ({ value, label: MATCH_TYPE_LABELS[value] }))

type Edit = (value: KeywordValue) => void
type SetValues = (
  ids: Iterable<string>,
  value: (row: { key: string; setting: KeywordSetting }) => KeywordValue
) => void

export function UpdateKeywordsApproval({
  args,
  checked,
  controls,
  disabled,
  onFieldEdit,
}: {
  args: UpdateKeywordsArgs
  // The request Google last answered for.
  checked: UpdateKeywordsArgs
  controls: ToolApprovalDecisionControls
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
}) {
  const [tab, setTab] = useState("all")
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set())
  const cancelled = useMemo(
    () => parseCancelledKeywordSettings(controls.retained),
    [controls.retained]
  )
  const rows = useMemo(() => keywordRows(args, checked, cancelled), [args, checked, cancelled])
  const byId = useMemo(() => new Map(rows.map((row) => [row.id, row])), [rows])
  const counts = keywordCounts(rows)
  const many = new Set(rows.map((row) => row.key)).size > 1
  const tools = rows.length >= TOOLS_FROM
  const accountIds = [...new Set(rows.filter((row) => !row.cancelled).map((row) => row.customerId))]
  const replaced = rows.filter((row) => !row.cancelled && replacesKeyword(row)).length

  // A review redraws the card, so cancelled settings live beside the request for Undo.
  const save = (
    changes: Record<string, unknown>[],
    nextCancelled: readonly CancelledKeywordSetting[]
  ) => {
    if (nextCancelled !== cancelled) controls.onRetain?.(nextCancelled)
    onFieldEdit("changes", changes)
  }
  const setValues: SetValues = (ids, value) => {
    save(editedKeywordChanges(args, new Set(ids), value), cancelled)
  }
  const cancel = (ids: Iterable<string>) => {
    const chosen = new Set(ids)
    const items = rows.flatMap((row) => {
      const keyword = row.change?.entry["keyword"]
      return chosen.has(row.id) && !row.cancelled && keyword && typeof keyword === "object"
        ? [
            {
              key: row.key,
              keyword: keyword as Record<string, unknown>,
              setting: row.setting,
              value: row.value,
            },
          ]
        : []
    })
    save(
      editedKeywordChanges(args, chosen, () => undefined),
      [...cancelled, ...items]
    )
  }
  const undo = (id: string) => {
    const item = cancelled.find((entry) => `${entry.key}|${entry.setting}` === id)
    if (item)
      save(
        restoredKeywordChanges(args, [item]),
        cancelled.filter((entry) => entry !== item)
      )
  }
  const liveOf = (match: (row: KeywordRow) => boolean) =>
    rows.filter((row) => !row.cancelled && match(row))
  const cancelCell = (row: KeywordRow) => (
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
    (row: KeywordRow): Edit =>
    (value) => {
      setValues([row.id], () => value)
    }
  const chosenMatchRows = [...selected].filter((id) => byId.get(id)?.setting === "match_type")
  const [adGroup, setAdGroup] = useState<string | null>(null)
  const parents = useMemo(() => adGroupParents(rows), [rows])
  const shown = adGroup === null ? rows : rows.filter((row) => keywordAdGroup(row) === adGroup)

  return (
    <div className="grid min-w-0 gap-3">
      <ChangeBanner
        aside={
          <p className="text-sm font-medium tabular-nums">
            {counts.apply.toLocaleString("en-GB")} {counts.apply === 1 ? "change" : "changes"}
          </p>
        }
        detail={keywordsBannerDetail(counts, accountIds, args.accounts)}
      />
      {replaced > 0 ? (
        <p className="text-muted-foreground text-sm">
          Google can't change a keyword's match type, so each new match type pauses the keyword and
          adds the same text with the new match type. Both happen together or not at all.
        </p>
      ) : null}
      {tools ? (
        <>
          <ChangeSummary
            lines={[
              ...KEYWORD_SETTINGS.map((setting): ChangeSummaryLine => {
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
                  label: KEYWORD_SETTING_TITLES[setting],
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
        <ParentTable
          columns={PARENT_COLUMNS}
          disabled={disabled}
          label="Ad Groups"
          onCancel={(key) => {
            cancel(liveOf((row) => keywordAdGroup(row) === key).map((row) => row.id))
          }}
          onSelect={setAdGroup}
          onUndo={(key) => {
            const items = cancelled.filter((item) => keywordAdGroup(item) === key)
            save(
              restoredKeywordChanges(args, items),
              cancelled.filter((item) => !items.includes(item))
            )
          }}
          rowNoun={["ad group", "ad groups"]}
          rows={parents}
          selected={adGroup}
        />
      ) : null}
      {many ? (
        <DataTable
          activeTab={tab}
          columns={COLUMNS}
          exportFilename="google-ads-keyword-changes.csv"
          onTabChange={setTab}
          pageSize={25}
          renderCell={(column, dataRow) => {
            const row = byId.get(String(dataRow["id"]))
            if (!row) return null
            if (column.key === "keyword") return <KeywordCell row={row} />
            if (column.key === "ad_group") return <AdGroupCell row={row} />
            if (column.key === "cancel") return cancelCell(row)
            if (column.key === "change")
              return (
                <ChangeCell
                  currency={keywordCurrency(args, row)}
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
          rows={shown.map((row) => ({
            ad_group: [row.adGroupName, row.campaignName].filter(Boolean).join(" · "),
            cancel: "",
            change: keywordValueText(row.setting, row.value, keywordCurrency(args, row)),
            id: row.id,
            keyword: row.text,
            setting: KEYWORD_SETTING_TITLES[row.setting],
          }))}
          {...(tools
            ? {
                searchable: true,
                selection: {
                  actions: (
                    <>
                      {chosenMatchRows.length > 0
                        ? MATCH_TYPES.map((match) => (
                            <Button
                              key={match}
                              disabled={disabled}
                              onClick={() => {
                                setValues(chosenMatchRows, () => match)
                                setSelected(new Set())
                              }}
                              size="sm"
                              type="button"
                              variant="outline"
                            >
                              Set to {MATCH_TYPE_LABELS[match]}
                            </Button>
                          ))
                        : null}
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
                    </>
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
        <SoleKeyword
          args={args}
          cancelCell={cancelCell}
          disabled={disabled}
          edit={edit}
          rows={rows}
        />
      )}
      <AddChange
        noun="Keyword"
        titles={KEYWORD_SETTING_TITLES}
        targets={args.changes.map((change) => ({
          key: change.key,
          name: rows.find((row) => row.key === change.key)?.text ?? change.label,
          options: addableSettings(checked, rows, change.key),
        }))}
        disabled={disabled}
        onAdd={(key, setting, value) => {
          save(addedKeywordChanges(args, key, setting, value), cancelled)
        }}
      />
      {keywordsNeedCheck(args, checked) && args.changes.length > 0 ? (
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

/** One keyword: where it is and its campaign's bidding, then each setting on one line. */
function SoleKeyword({
  args,
  cancelCell,
  disabled,
  edit,
  rows,
}: {
  args: UpdateKeywordsArgs
  cancelCell: (row: KeywordRow) => ReactNode
  disabled: boolean
  edit: (row: KeywordRow) => Edit
  rows: readonly KeywordRow[]
}) {
  const [first] = rows
  if (!first) return null
  const campaign = first.campaignName
    ? `${first.campaignName}${first.strategyName ? `, which uses ${first.strategyName}` : ""}`
    : null
  const where = [
    first.matchType ? `${MATCH_TYPE_LABELS[first.matchType]} match` : null,
    first.adGroupName ? `in ${first.adGroupName}` : null,
    campaign ? `(${campaign})` : null,
  ]
    .filter(Boolean)
    .join(" ")
  return (
    <section aria-label={first.text} className="overflow-hidden rounded-lg border">
      <p className="text-muted-foreground border-b px-3 py-2 text-sm">
        <span className="text-foreground font-medium">{first.text}</span>
        {where ? `, ${where}` : ""}.
      </p>
      <ul className="divide-y">
        {rows.map((row) => (
          <li
            key={row.id}
            className="grid grid-cols-[9rem_minmax(0,1fr)_auto] items-start gap-3 px-3 py-2"
          >
            <div className="grid min-w-0 gap-0.5 pt-1 text-sm">
              <span className="font-medium">{KEYWORD_SETTING_TITLES[row.setting]}</span>
              <Problem row={row} />
            </div>
            <ChangeCell
              currency={keywordCurrency(args, row)}
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

function settingTabs(byId: ReadonlyMap<string, KeywordRow>): DataTableTab[] {
  const live = (dataRow: DataRow, match: (row: KeywordRow) => boolean) => {
    const row = byId.get(String(dataRow["id"]))
    return row !== undefined && !row.cancelled && match(row)
  }
  return [
    { id: "all", label: "All", match: () => true },
    ...KEYWORD_SETTINGS.map((setting) => ({
      hideWhenEmpty: true,
      id: setting,
      label: KEYWORD_SETTING_TITLES[setting],
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

function Problem({ row }: { row: KeywordRow }) {
  return !row.cancelled && row.problem ? (
    <span className="text-destructive text-xs wrap-anywhere whitespace-normal">{row.problem}</span>
  ) : null
}

function KeywordCell({ row }: { row: KeywordRow }) {
  return (
    <div className="grid min-w-0 gap-0.5 text-sm">
      <span className="font-medium wrap-anywhere whitespace-normal">{row.text}</span>
      {row.matchType ? (
        <span className="text-muted-foreground text-xs">{MATCH_TYPE_LABELS[row.matchType]}</span>
      ) : null}
      <Problem row={row} />
    </div>
  )
}

/** The ad group, then the campaign with the strategy that decides whether keyword bids count. */
function AdGroupCell({ row }: { row: KeywordRow }) {
  return (
    <div className="grid min-w-0 gap-0.5 text-sm">
      <span className="wrap-anywhere whitespace-normal">{row.adGroupName ?? "—"}</span>
      {row.campaignName ? (
        <span className="text-muted-foreground text-xs wrap-anywhere whitespace-normal">
          {row.campaignName}
          {row.strategyName ? ` · ${row.strategyName}` : ""}
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
  row: KeywordRow
}) {
  const was = keywordValueText(row.setting, row.was, currency)
  if (row.cancelled)
    return (
      <span className="text-muted-foreground pt-1 text-sm line-through">
        {was} → {keywordValueText(row.setting, row.value, currency)}
      </span>
    )
  return (
    <div className="grid min-w-0 gap-1">
      <div className="flex min-w-0 flex-wrap items-center gap-2 text-sm">
        <span className="text-muted-foreground wrap-anywhere whitespace-normal">{was} →</span>
        <SettingEditor
          currency={currency}
          disabled={disabled}
          label={`New ${KEYWORD_SETTING_TITLES[row.setting].toLowerCase()} for ${row.text}`}
          onChange={onChange}
          row={row}
        />
        {row.unchanged ? <Badge variant="secondary">Already Set</Badge> : null}
      </div>
      {replacesKeyword(row) && row.was !== undefined ? (
        <span className="text-muted-foreground text-xs">
          Pauses the {keywordValueText("match_type", row.was, null).toLowerCase()} keyword and adds
          a {keywordValueText("match_type", row.value, null).toLowerCase()} one.
        </span>
      ) : null}
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
  row: KeywordRow
}): ReactNode {
  const { setting, value } = row
  if (setting === "match_type")
    return (
      <SegmentedChoice
        ariaLabel={label}
        compact
        disabled={disabled}
        onChange={onChange}
        options={MATCH_OPTIONS}
        value={MATCH_TYPES.find((item) => item === value) ?? null}
      />
    )
  if (setting === "custom_parameters")
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
        value={
          Array.isArray(value) ? parametersText(value as { key: string; value: string }[]) : ""
        }
      />
    )
  if (setting === "final_urls" || setting === "final_mobile_urls")
    return (
      <CommittedInput
        ariaLabel={label}
        className="h-7 min-w-48 flex-1 text-sm"
        disabled={disabled}
        onCommit={(next) => {
          const parsed = parseUrls(next)
          if (parsed) onChange(parsed)
        }}
        placeholder="None, so the ad's URL is used"
        value={Array.isArray(value) ? (value as string[]).join(" ") : ""}
      />
    )
  if (setting === "cpc_bid") {
    const symbol = currency ? currencySymbol(currency) : null
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
          className={cn("h-7 w-32 text-sm tabular-nums", symbol && "pl-6")}
          disabled={disabled}
          onCommit={(next) => {
            const trimmed = next.trim()
            const number = Number(trimmed)
            // An empty bid makes the keyword use its ad group's bid.
            if (!trimmed) onChange(null)
            else if (Number.isFinite(number) && number > 0) onChange(canonicalMoney(trimmed))
          }}
          placeholder="Ad group's bid"
          value={typeof value === "string" ? moneyInput(value) : ""}
        />
      </div>
    )
  }
  return (
    <CommittedInput
      ariaLabel={label}
      className="h-7 min-w-48 flex-1 text-sm"
      disabled={disabled}
      onCommit={(next) => {
        onChange(next.trim() || null)
      }}
      placeholder="None"
      value={typeof value === "string" ? value : ""}
    />
  )
}

/** One control that edits every keyword in a summary line, where that makes sense. */
function EveryAction({
  args,
  disabled,
  rows,
  setting,
  setValues,
}: {
  args: UpdateKeywordsArgs
  disabled: boolean
  rows: readonly KeywordRow[]
  setting: KeywordSetting
  setValues: SetValues
}): ReactNode {
  const [first] = rows
  if (!first || rows.length < 2) return null
  const ids = rows.map((row) => row.id)
  if (setting === "match_type")
    return (
      <SegmentedChoice<KeywordMatchType>
        ariaLabel="Match type for every keyword in this line"
        compact
        disabled={disabled}
        onChange={(value) => {
          setValues(ids, () => value)
        }}
        options={MATCH_OPTIONS}
        value={
          rows.every((row) => row.value === first.value)
            ? (MATCH_TYPES.find((item) => item === first.value) ?? null)
            : null
        }
      />
    )
  if (setting !== "cpc_bid") return null
  // Each new bid is the live one changed by the same percentage.
  const byKey = new Map(rows.map((row) => [row.key, row]))
  return (
    <CommittedInput
      ariaLabel="Change every max CPC in this line by a percentage"
      className="h-7 w-28 text-sm tabular-nums"
      disabled={disabled}
      onCommit={(next) => {
        const percent = Number(next.trim().replace(/%$/, ""))
        if (!next.trim() || !Number.isFinite(percent) || percent <= -100) return
        setValues(ids, ({ key }) => {
          const row = byKey.get(key)
          const was = typeof row?.was === "string" ? row.was : null
          return was && row
            ? scaledMoney(was, percent, keywordCurrency(args, row))
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
  row: KeywordRow
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
