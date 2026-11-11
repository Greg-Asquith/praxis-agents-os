// apps/web/src/integrations/google_ads/components/create-ads-approval.tsx

import { ChevronLeftIcon, ChevronRightIcon, PlusIcon, XIcon } from "lucide-react"
import { useMemo, useState } from "react"

import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-types"
import type { EditedValue } from "@/components/tool-ui/edited-values"
import { Button } from "@/components/ui/button"
import {
  DataTable,
  type DataColumn,
  type DataRow,
  type DataTableTab,
} from "@/components/ui/data-table"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { AttentionLine } from "@/integrations/ads/components/attention-line"
import { ChangeSummary, type ChangeSummaryLine } from "@/integrations/ads/components/change-summary"
import { ParentTable, type ParentRow } from "@/integrations/ads/components/parent-table"
import { StatusChoice } from "@/integrations/ads/components/status-choice"
import { AdCopyEditor } from "@/integrations/google_ads/components/ad-copy-editor"
import {
  AdGroupCombobox,
  type ChosenAdGroup,
} from "@/integrations/google_ads/components/ad-group-combobox"
import { CheckChanges } from "@/integrations/google_ads/components/check-changes"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import {
  adGroupName,
  adGroupParents,
  adRows,
  adsNeedCheck,
  adsRequestProblems,
  canCheckAds,
  cancelInAdGroups,
  createAdsCounts,
  parseAdGroup,
  parseRetained,
  problemsIn,
  restoreAdGroups,
  serializeAds,
  serializeRetained,
  sharedValue,
  type AdGroupParent,
  type AdGroupTarget,
  type AdRow,
  type CreateAdsArgs,
  type CreateAdsRetained,
  type DraftAd,
} from "@/integrations/google_ads/lib/create-ads"

const TOOL = "google_ads_create_ads"
// Below this many ads the table's search only adds noise.
const SEARCH_FROM = 10
// Google creates one ad in at most this many ad groups.
const MAX_AD_GROUPS_PER_AD = 10
const NONE = new Set<string>()

const PARENT_COLUMNS: DataColumn[] = [
  { key: "ads", kind: "number", label: "Ads", width: 90 },
  { key: "problems", kind: "text", label: "Problems", width: 140 },
]

const COLUMNS: DataColumn[] = [
  { key: "headline", kind: "text", label: "Headline 1", width: 320 },
  { key: "headlines", kind: "number", label: "Headlines", width: 100 },
  { key: "descriptions", kind: "number", label: "Descriptions", width: 110 },
  { key: "cancel", kind: "text", label: "Cancel", width: 80 },
]

const TABS: DataTableTab[] = [
  { id: "all", label: "All", match: () => true },
  {
    id: "attention",
    label: "Needs Attention",
    hideWhenEmpty: true,
    match: (row) => row["attention"] === "yes",
  },
]

export function CreateAdsApproval({
  args,
  checked,
  controls,
  disabled,
  onFieldEdit,
}: {
  args: CreateAdsArgs
  // The request Google last answered for.
  checked: CreateAdsArgs
  controls: ToolApprovalDecisionControls
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
}) {
  const rows = useMemo(() => adRows(args), [args])
  const counts = createAdsCounts(rows)
  // Cancelled ads and ad groups with no ads yet. A review redraws the card, so they live beside it.
  const retained = useMemo(() => parseRetained(controls.retained, args), [controls.retained, args])
  const parents = useMemo(() => adGroupParents(args, rows, retained), [args, rows, retained])
  const [chosen, setChosen] = useState<string | null>(null)
  const [openAd, setOpenAd] = useState<number | null>(null)
  const [finding, setFinding] = useState(false)
  const [tab, setTab] = useState("all")
  const firstProblem = parents.find((parent) => parent.state === "live" && parent.problems > 0)
  const group =
    parents.find((parent) => parent.target.key === chosen) ?? firstProblem ?? parents[0] ?? null
  const groupKey = group?.target.key ?? ""
  const groupRows = useMemo(
    () => group?.ads.flatMap((index) => rows[index] ?? []) ?? [],
    [group, rows]
  )
  const openRow =
    groupRows.find((row) => row.index === openAd) ??
    groupRows.find((row) => problemsIn(row, groupKey).length > 0) ??
    groupRows[0]

  const save = (ads: readonly DraftAd[], nextRetained: CreateAdsRetained = retained) => {
    controls.onRetain?.(serializeRetained(nextRetained))
    onFieldEdit("ads", serializeAds(ads))
  }
  const apply = (edit: { ads: DraftAd[]; retained: CreateAdsRetained }) => {
    save(edit.ads, edit.retained)
  }
  const editAd = (index: number, patch: Partial<DraftAd>) => {
    save(args.ads.map((ad, at) => (at === index ? { ...ad, ...patch } : ad)))
  }
  const cancelGroup = (key: string) => {
    if (retained.adGroups.some((item) => item.key === key)) {
      save(args.ads, {
        ...retained,
        adGroups: retained.adGroups.filter((item) => item.key !== key),
      })
      return
    }
    apply(cancelInAdGroups(args.ads, retained, () => new Set([key])))
  }
  const cancelAd = (index: number) => {
    apply(
      cancelInAdGroups(args.ads, retained, (_, at) => (at === index ? new Set([groupKey]) : NONE))
    )
  }
  const cancelProblems = () => {
    apply(
      cancelInAdGroups(args.ads, retained, (ad, at) => {
        const issues = rows[at]?.issues ?? []
        if (issues.some((issue) => issue.adGroup === null))
          return new Set(ad.adGroups.map((item) => item.key))
        return new Set(issues.flatMap((issue) => issue.adGroup ?? []))
      })
    )
  }
  const addAdGroups = (picked: readonly ChosenAdGroup[]) => {
    const known = new Set(parents.map((parent) => parent.target.key))
    const fresh = picked.flatMap((item) => parseAdGroup(item.raw) ?? [])
    const added = fresh.filter((item) => !known.has(item.key))
    if (added.length > 0)
      save(args.ads, { ...retained, adGroups: [...retained.adGroups, ...added] })
    setChosen(fresh.at(-1)?.key ?? chosen)
    setOpenAd(null)
    setFinding(false)
  }
  const copyHere = (index: number, target: AdGroupTarget) => {
    const ad = args.ads[index]
    if (ad) editAd(index, { adGroups: [...ad.adGroups, target] })
    setOpenAd(index)
  }
  const newAd = (target: AdGroupTarget) => {
    save([...args.ads, blankAd(args.ads, target)])
    setOpenAd(args.ads.length)
  }

  const wholeRequest = adsRequestProblems(args)
  const tableRows = useMemo<DataRow[]>(
    () =>
      groupRows.map((row) => ({
        attention: problemsIn(row, groupKey).length > 0 ? "yes" : "no",
        cancel: "",
        descriptions: row.ad.descriptions.length,
        headline: row.ad.headlines[0]?.text ?? "",
        headlines: row.ad.headlines.length,
        key: String(row.index),
      })),
    [groupKey, groupRows]
  )
  const parentRows = useMemo<ParentRow[]>(() => parents.map(parentRow), [parents])
  const others = rows.filter(
    (row) =>
      row.ad.adGroups.length < MAX_AD_GROUPS_PER_AD &&
      !row.ad.adGroups.some((item) => item.key === groupKey)
  )
  const position = groupRows.findIndex((row) => row.index === openRow?.index)

  return (
    <div className="grid min-w-0 gap-3">
      <StatusChoice
        activeNote="Active, pending approval. Will go live once approved by Google."
        disabled={disabled}
        onChange={(status) => {
          onFieldEdit("status", status === "active" ? "ENABLED" : "PAUSED")
        }}
        pausedNote="Paused. Will not appear or spend until activated."
        value={args.status === "ENABLED" ? "active" : "paused"}
      />
      {wholeRequest.length > 0 ? (
        <ul className="text-destructive grid gap-0.5 text-sm" role="alert">
          {wholeRequest.map((problem) => (
            <li key={problem} className="wrap-anywhere">
              {problem}
            </li>
          ))}
        </ul>
      ) : null}
      {rows.length > 1 ? (
        <SharedSettings
          ads={args.ads}
          cancelled={retained.ads.reduce((total, ad) => total + ad.adGroups.length, 0)}
          disabled={disabled}
          onCancelProblems={cancelProblems}
          onEditEvery={(patch) => {
            save(args.ads.map((ad) => ({ ...ad, ...patch })))
          }}
          onRestore={() => {
            apply(restoreAdGroups(args.ads, retained, null))
          }}
          problems={counts.problems}
        />
      ) : null}
      <AttentionLine
        count={counts.problems}
        onShow={() => {
          setChosen(firstProblem?.target.key ?? null)
          setOpenAd(null)
          setTab("attention")
        }}
      />
      <div className="grid min-w-0 gap-1.5">
        {finding ? (
          <div className="flex min-w-0 items-center gap-2">
            <div className="min-w-0 flex-1">
              <AdGroupCombobox
                chosen={[]}
                disabled={disabled}
                fieldKey="ads"
                onChange={addAdGroups}
                toolName={TOOL}
              />
            </div>
            <Button
              disabled={disabled}
              onClick={() => {
                setFinding(false)
              }}
              size="sm"
              type="button"
              variant="ghost"
            >
              Cancel
            </Button>
          </div>
        ) : (
          <Button
            className="w-fit justify-self-end"
            disabled={disabled}
            onClick={() => {
              setFinding(true)
            }}
            size="sm"
            type="button"
            variant="ghost"
          >
            <PlusIcon aria-hidden="true" />
            Add Ad Group
          </Button>
        )}
        <ParentTable
          columns={PARENT_COLUMNS}
          disabled={disabled}
          label="Ad Groups"
          onCancel={cancelGroup}
          onSelect={(key) => {
            if (key === null) return
            setChosen(key)
            setOpenAd(null)
            setTab("all")
          }}
          onUndo={(key) => {
            apply(restoreAdGroups(args.ads, retained, key))
          }}
          rowNoun={["ad group", "ad groups"]}
          rows={parentRows}
          selected={group?.target.key ?? null}
        />
      </div>
      {group?.state === "cancelled" ? (
        <p className="text-muted-foreground flex flex-wrap items-center gap-2 text-sm">
          {group.name} is cancelled, so none of its {approvalCountLine(group.cancelled, "ad")} will
          be created.
          <Button
            disabled={disabled}
            onClick={() => {
              apply(restoreAdGroups(args.ads, retained, group.target.key))
            }}
            size="sm"
            type="button"
            variant="outline"
          >
            Undo
          </Button>
        </p>
      ) : group ? (
        <DataTable
          key={group.target.key}
          activeTab={tab}
          columns={COLUMNS}
          exportFilename="google-ads-new-ads.csv"
          onTabChange={setTab}
          pageSize={25}
          renderCell={(column, row) => {
            const adRow = rows[Number(row["key"])]
            if (!adRow) return null
            if (column.key === "headline")
              return <HeadlineCell problem={problemsIn(adRow, groupKey)[0] ?? null} row={adRow} />
            if (column.key === "cancel")
              return (
                <Button
                  aria-label={`Cancel ad ${String(adRow.index + 1)}`}
                  disabled={disabled}
                  onClick={(event) => {
                    // The row opens the ad on click; cancelling shouldn't.
                    event.stopPropagation()
                    cancelAd(adRow.index)
                  }}
                  size="icon-xs"
                  title="Cancel This Change"
                  type="button"
                  variant="ghost"
                >
                  <XIcon />
                </Button>
              )
            return null
          }}
          rowClassName={(row) =>
            Number(row["key"]) === openRow?.index
              ? "bg-muted/70 shadow-[inset_3px_0_0_var(--primary)]"
              : undefined
          }
          onRowClick={(row) => {
            setOpenAd(Number(row["key"]))
          }}
          rowDetails={false}
          rowNoun={["ad", "ads"]}
          rows={tableRows}
          searchable={groupRows.length >= SEARCH_FROM}
          summary={
            <NewAd
              disabled={disabled}
              onCopy={(index) => {
                copyHere(index, group.target)
              }}
              onNew={() => {
                newAd(group.target)
              }}
              others={others}
            />
          }
          tabs={TABS}
        />
      ) : null}
      {openRow && group?.state === "live" ? (
        <AdEditor
          key={openRow.index}
          args={args}
          disabled={disabled}
          groupKey={groupKey}
          onEdit={(patch) => {
            editAd(openRow.index, patch)
          }}
          onOpen={(at) => {
            setOpenAd(groupRows[at]?.index ?? null)
          }}
          position={{ at: position, total: groupRows.length }}
          row={openRow}
        />
      ) : null}
      {/* At the end, beside the approve button that waits on it. */}
      {adsNeedCheck(args, checked) && args.ads.length > 0 ? (
        <CheckChanges
          canCheck={canCheckAds(args)}
          disabled={disabled}
          label={args.checks.unavailable ? "Check Again" : "Check Changes"}
          note="Google hasn't checked these changes yet."
          onCheck={controls.onReview}
          submitting={controls.submitting}
        />
      ) : null}
    </div>
  )
}

function parentRow(parent: AdGroupParent): ParentRow {
  return {
    cancelled: parent.state === "cancelled",
    context: parent.campaignName,
    key: parent.target.key,
    name: parent.name,
    problems: parent.state === "live" ? parent.problems : 0,
    values: {
      ads: parent.state === "cancelled" ? parent.cancelled : parent.ads.length,
      ...(parent.state === "new" ? { problems: "No ads yet" } : {}),
    },
  }
}

/** A new ad in one ad group, with the links every ad already shares. */
function blankAd(ads: readonly DraftAd[], target: AdGroupTarget): DraftAd {
  return {
    adGroups: [target],
    descriptions: [],
    entry: {},
    finalUrl: sharedValue(ads, "finalUrl") ?? "",
    headlines: [],
    mobileFinalUrl: "",
    path1: sharedValue(ads, "path1") ?? "",
    path2: sharedValue(ads, "path2") ?? "",
  }
}

function adTitle(row: AdRow): string {
  return row.ad.headlines[0]?.text.trim() ? row.ad.headlines[0].text : `Ad ${String(row.index + 1)}`
}

/** The add line under an ad group's ads: one of the other ads here too, or a new one. */
function NewAd({
  disabled,
  onCopy,
  onNew,
  others,
}: {
  disabled: boolean
  onCopy: (index: number) => void
  onNew: () => void
  // Ads in the request that aren't in this ad group yet.
  others: readonly AdRow[]
}) {
  return (
    <span className="flex flex-wrap items-center gap-2">
      {others.length > 0 ? (
        <Select<string>
          disabled={disabled}
          onValueChange={(value) => {
            if (value !== null) onCopy(Number(value))
          }}
          value={null}
        >
          <SelectTrigger aria-label="Use another ad here too" className="w-56" size="sm">
            <SelectValue placeholder="Use Another Ad Here" />
          </SelectTrigger>
          <SelectContent align="start">
            <SelectGroup>
              {others.map((row) => (
                <SelectItem key={row.index} label={adTitle(row)} value={String(row.index)}>
                  {adTitle(row)}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
      ) : null}
      <Button disabled={disabled} onClick={onNew} size="sm" type="button" variant="outline">
        <PlusIcon aria-hidden="true" />
        New Ad
      </Button>
    </span>
  )
}

function HeadlineCell({ problem, row }: { problem: string | null; row: AdRow }) {
  return (
    <span className="grid min-w-0 gap-0.5 whitespace-normal">
      <span className="font-medium wrap-anywhere">{adTitle(row)}</span>
      {problem ? <span className="text-destructive text-xs wrap-anywhere">{problem}</span> : null}
    </span>
  )
}

/** Settings every ad shares, edited once, with the lines for problems and cancelled ads. */
function SharedSettings({
  ads,
  cancelled,
  disabled,
  onCancelProblems,
  onEditEvery,
  onRestore,
  problems,
}: {
  ads: readonly DraftAd[]
  cancelled: number
  disabled: boolean
  onCancelProblems: () => void
  onEditEvery: (patch: Partial<DraftAd>) => void
  onRestore: () => void
  problems: number
}) {
  const finalUrl = sharedValue(ads, "finalUrl")
  const path1 = sharedValue(ads, "path1")
  const path2 = sharedValue(ads, "path2")
  const lines: ChangeSummaryLine[] = [
    {
      id: "final_url",
      label: "Final URL for every ad",
      count: finalUrl === null ? 0 : ads.length,
      action: (
        <Input
          aria-label="Final URL for every ad"
          className="w-80 max-w-full text-sm"
          disabled={disabled}
          onChange={(event) => {
            onEditEvery({ finalUrl: event.currentTarget.value })
          }}
          value={finalUrl ?? ""}
        />
      ),
    },
    {
      id: "paths",
      label: "Display paths for every ad",
      count: path1 === null || path2 === null ? 0 : ads.length,
      action: (
        <span className="flex gap-2">
          <Input
            aria-label="Path 1 for every ad"
            className="w-32 text-sm"
            disabled={disabled}
            onChange={(event) => {
              onEditEvery({ path1: event.currentTarget.value })
            }}
            value={path1 ?? ""}
          />
          <Input
            aria-label="Path 2 for every ad"
            className="w-28 text-sm"
            disabled={disabled}
            onChange={(event) => {
              onEditEvery({ path2: event.currentTarget.value })
            }}
            value={path2 ?? ""}
          />
        </span>
      ),
    },
    {
      id: "attention",
      label: "Needs Attention",
      count: problems,
      tone: "danger",
      action: (
        <Button
          disabled={disabled}
          onClick={onCancelProblems}
          size="sm"
          type="button"
          variant="outline"
        >
          Cancel These {String(problems)}
        </Button>
      ),
    },
    {
      id: "cancelled",
      label: "Cancelled",
      count: cancelled,
      action: (
        <Button disabled={disabled} onClick={onRestore} size="sm" type="button" variant="outline">
          Restore
        </Button>
      ),
    },
  ]
  return <ChangeSummary lines={lines} />
}

function AdEditor({
  args,
  disabled,
  groupKey,
  onEdit,
  onOpen,
  position,
  row,
}: {
  args: CreateAdsArgs
  disabled: boolean
  // The ad group whose ads the editor steps through.
  groupKey: string
  onEdit: (patch: Partial<DraftAd>) => void
  // Opens another of the ad group's ads, by its place in the ad group.
  onOpen: (at: number) => void
  // Which of the ad group's ads this is.
  position: { at: number; total: number }
  row: AdRow
}) {
  const { ad } = row
  const many = position.total > 1
  const elsewhere = ad.adGroups.filter((group) => group.key !== groupKey)
  const problems = problemsIn(row, groupKey)
  return (
    <section
      aria-label={many ? `Ad ${String(position.at + 1)}` : "Ad"}
      className="grid min-w-0 gap-4 rounded-lg border px-3 py-3"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium">
          {many ? `Ad ${String(position.at + 1)} of ${String(position.total)}` : "Ad"}
          <span className="text-muted-foreground font-normal">
            {" "}
            · {approvalCountLine(ad.headlines.length, "headline")} ·{" "}
            {approvalCountLine(ad.descriptions.length, "description")}
          </span>
        </p>
        {many ? (
          <span className="flex gap-1">
            <Button
              disabled={position.at <= 0}
              onClick={() => {
                onOpen(position.at - 1)
              }}
              size="sm"
              type="button"
              variant="ghost"
            >
              <ChevronLeftIcon />
              Previous
            </Button>
            <Button
              disabled={position.at >= position.total - 1}
              onClick={() => {
                onOpen(position.at + 1)
              }}
              size="sm"
              type="button"
              variant="ghost"
            >
              Next
              <ChevronRightIcon />
            </Button>
          </span>
        ) : null}
      </div>
      {elsewhere.length > 0 ? (
        <p className="text-muted-foreground text-sm wrap-anywhere">
          Also created in {elsewhere.map((group) => adGroupName(group, args.checks)).join(", ")}.
          Edits change it in every one.
        </p>
      ) : null}
      {problems.length > 0 ? (
        <ul className="text-destructive grid gap-0.5 text-sm" role="alert">
          {problems.map((problem) => (
            <li key={problem} className="wrap-anywhere">
              {problem}
            </li>
          ))}
        </ul>
      ) : null}
      <AdCopyEditor ad={ad} disabled={disabled} onEdit={onEdit} />
    </section>
  )
}
