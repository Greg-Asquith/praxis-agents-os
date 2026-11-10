// apps/web/src/integrations/google_ads/components/create-keywords-approval.tsx

import { PlusIcon, XIcon } from "lucide-react"
import { useMemo, useState, type ClipboardEvent } from "react"

import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-types"
import type { EditedValue } from "@/components/tool-ui/edited-values"
import { Button } from "@/components/ui/button"
import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"
import { Input } from "@/components/ui/input"
import { AttentionLine } from "@/integrations/ads/components/attention-line"
import { ChangeSummary } from "@/integrations/ads/components/change-summary"
import { CommittedInput } from "@/integrations/ads/components/committed-input"
import { SegmentedChoice } from "@/integrations/ads/components/controls"
import { ParentTable, type ParentRow } from "@/integrations/ads/components/parent-table"
import { StatusChoice } from "@/integrations/ads/components/status-choice"
import {
  parseKeywordLines,
  type KeywordMatchType,
  type PastedKeyword,
} from "@/integrations/ads/lib/keyword-notation"
import {
  AdGroupCombobox,
  type ChosenAdGroup,
} from "@/integrations/google_ads/components/ad-group-combobox"
import { CheckChanges } from "@/integrations/google_ads/components/check-changes"
import { MatchTypeCell } from "@/integrations/google_ads/components/new-ad-groups"
import { approvalCountLine } from "@/integrations/google_ads/lib/copy"
import type { DraftKeyword } from "@/integrations/google_ads/lib/create-ad-groups"
import {
  keywordAdGroupRows,
  keywordCounts,
  keywordProblem,
  keywordsNeedCheck,
  parseCreateKeywordsArgs,
  serializeEntries,
  type CreateKeywordsArgs,
  type KeywordAdGroupRow,
  type KeywordEntry,
} from "@/integrations/google_ads/lib/create-keywords"
import { MATCH_TYPE_LABELS, MATCH_TYPES } from "@/integrations/google_ads/lib/negative-keywords"

const TOOL = "google_ads_create_keywords"
const MATCH_OPTIONS = MATCH_TYPES.map((value) => ({ value, label: MATCH_TYPE_LABELS[value] }))
// Below this many keywords the summary, search, and tabs only add noise.
const TOOLS_FROM = 10

const PARENT_COLUMNS: DataColumn[] = [
  { key: "keywords", kind: "number", label: "Keywords", width: 100 },
  { key: "bid", kind: "text", label: "Bid", width: 180 },
  { key: "problems", kind: "text", label: "Problems", width: 140 },
]

// A cancelled ad group keeps its keywords for Undo; a new one has none until one is added.
type GroupState = "live" | "cancelled" | "new"
type Group = KeywordAdGroupRow & { state: GroupState }

export function CreateKeywordsApproval({
  args,
  checked,
  controls,
  disabled,
  onFieldEdit,
}: {
  args: CreateKeywordsArgs
  // The request Google last answered for.
  checked: CreateKeywordsArgs
  controls: ToolApprovalDecisionControls
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
}) {
  // Ad groups outside the request, cancelled or new. A review redraws the card, so they live
  // beside it.
  const parked = useMemo(() => parkedEntries(controls.retained), [controls.retained])
  const groups = useMemo<Group[]>(
    () => [
      ...keywordAdGroupRows(args, checked).map((row) => ({ ...row, state: "live" as const })),
      ...keywordAdGroupRows({ ...checked, entries: parked }, checked).map((row) => ({
        ...row,
        state: row.entry.keywords.length > 0 ? ("cancelled" as const) : ("new" as const),
      })),
    ],
    [args, checked, parked]
  )
  const counts = keywordCounts(args, checked)
  const [chosen, setChosen] = useState<string | null>(null)
  const [finding, setFinding] = useState(false)
  const tools = counts.keywords >= TOOLS_FROM
  const firstProblem = groups.find((group) => group.state === "live" && group.problems > 0)
  const open =
    groups.find((group) => group.entry.key === chosen) ?? firstProblem ?? groups[0] ?? null

  const save = (entries: readonly KeywordEntry[], nextParked: readonly KeywordEntry[]) => {
    controls.onRetain?.(serializeEntries(nextParked))
    onFieldEdit("entries", serializeEntries(entries))
  }
  const cancel = (key: string) => {
    const entry = args.entries.find((item) => item.key === key)
    // A new ad group with no keywords just leaves the card.
    if (!entry) {
      save(
        args.entries,
        parked.filter((item) => item.key !== key)
      )
      return
    }
    save(
      args.entries.filter((item) => item.key !== key),
      [...parked, entry]
    )
  }
  const restore = (key: string, keywords?: DraftKeyword[]) => {
    const entry = parked.find((item) => item.key === key)
    if (!entry) return
    save(
      [...args.entries, keywords ? { ...entry, keywords } : entry],
      parked.filter((item) => item.key !== key)
    )
  }
  const editKeywords = (key: string, keywords: DraftKeyword[]) => {
    if (parked.some((item) => item.key === key)) {
      if (keywords.length > 0) restore(key, keywords)
      return
    }
    // An ad group left with no keywords is cancelled, so Undo brings its keywords back.
    if (keywords.length === 0) {
      cancel(key)
      return
    }
    save(
      args.entries.map((item) => (item.key === key ? { ...item, keywords } : item)),
      parked
    )
  }
  const editKeyword = (group: Group, index: number, patch: Partial<DraftKeyword>) => {
    editKeywords(
      group.entry.key,
      group.entry.keywords.map((keyword, at) => (at === index ? { ...keyword, ...patch } : keyword))
    )
  }
  const addKeywords = (group: Group, pasted: readonly PastedKeyword[]) => {
    const known = new Set(group.entry.keywords.map(sameKeyword))
    const fresh = pasted.filter((keyword) => !known.has(sameKeyword(keyword)))
    editKeywords(group.entry.key, [
      ...group.entry.keywords,
      ...fresh.map((keyword) => ({ ...keyword, cpcBid: "", finalUrl: "" })),
    ])
  }
  const addAdGroups = (picked: readonly ChosenAdGroup[]) => {
    const known = new Set([...args.entries, ...parked].map((entry) => entry.key))
    const fresh = picked.filter((item) => !known.has(item.key))
    if (fresh.length > 0)
      save(args.entries, [...parked, ...fresh.map((item) => ({ ...item, keywords: [] }))])
    setChosen(picked.at(-1)?.key ?? chosen)
    setFinding(false)
  }
  const cancelProblems = () => {
    const kept = args.entries.map((entry) => ({
      ...entry,
      keywords: entry.keywords.filter((keyword) => !keywordProblem(checked, entry, keyword)),
    }))
    save(
      kept.filter((entry) => entry.keywords.length > 0),
      [...parked, ...args.entries.filter((_, at) => kept[at]?.keywords.length === 0)]
    )
  }
  const setBidForAll = (bid: string) => {
    save(
      args.entries.map((entry) =>
        checked.adGroups.get(entry.key)?.usesCpcBid === false
          ? entry
          : { ...entry, keywords: entry.keywords.map((keyword) => ({ ...keyword, cpcBid: bid })) }
      ),
      parked
    )
  }

  const acceptsBids = (group: Group) => checked.adGroups.get(group.entry.key)?.usesCpcBid ?? true
  const anyBids = open !== null && acceptsBids(open)
  const anyUrl = open?.entry.keywords.some((keyword) => keyword.finalUrl) ?? false
  const columns = useMemo<DataColumn[]>(
    () => [
      { key: "keyword", kind: "text", label: "Keyword", width: 300 },
      { key: "match", kind: "text", label: "Match Type", width: 130 },
      ...(anyBids ? [{ key: "bid", kind: "text" as const, label: "Max CPC", width: 130 }] : []),
      // Final URLs are rare, so the column waits in the chooser until a keyword has one.
      { key: "url", kind: "text", label: "Final URL", width: 220, hidden: !anyUrl },
      { key: "cancel", kind: "text", label: "Cancel", width: 60 },
    ],
    [anyBids, anyUrl]
  )
  const tableRows = useMemo<DataRow[]>(
    () =>
      open?.entry.keywords.map((keyword, index) => ({
        bid: keyword.cpcBid,
        id: String(index),
        index,
        keyword: keyword.text,
        match: MATCH_TYPE_LABELS[keyword.matchType],
        url: keyword.finalUrl,
      })) ?? [],
    [open]
  )
  const parents = useMemo<ParentRow[]>(() => groups.map(parentRow), [groups])

  return (
    <div className="grid min-w-0 gap-3">
      <StatusChoice
        activeNote="Active. Will start showing for searches once approved."
        disabled={disabled}
        onChange={(status) => {
          onFieldEdit("status", status === "active" ? "ENABLED" : "PAUSED")
        }}
        pausedNote="Paused. Will not appear or spend until activated."
        value={args.status === "ENABLED" ? "active" : "paused"}
      />
      {tools ? (
        <ChangeSummary
          lines={[
            {
              id: "default_bid",
              label: "Use the Ad Group's Default Bid",
              detail: "unless you set one",
              count: groups.reduce(
                (total, group) =>
                  group.state === "live" && acceptsBids(group)
                    ? total + group.entry.keywords.filter((keyword) => !keyword.cpcBid).length
                    : total,
                0
              ),
              action: (
                <CommittedInput
                  ariaLabel="Max CPC for every keyword"
                  className="w-32 text-sm"
                  disabled={disabled}
                  onCommit={(bid) => {
                    if (bid.trim()) setBidForAll(bid.trim())
                  }}
                  placeholder="Set for all"
                  value=""
                />
              ),
            },
            {
              id: "attention",
              label: "Needs Attention",
              count: counts.problems,
              onSelect: () => {
                setChosen(firstProblem?.entry.key ?? null)
              },
              tone: "danger",
              action: (
                <Button
                  disabled={disabled}
                  onClick={cancelProblems}
                  size="sm"
                  type="button"
                  variant="outline"
                >
                  Cancel These {String(counts.problems)}
                </Button>
              ),
            },
          ]}
        />
      ) : (
        <AttentionLine
          count={counts.problems}
          onShow={() => {
            setChosen(firstProblem?.entry.key ?? null)
          }}
        />
      )}
      <div className="grid min-w-0 gap-1.5">
        {finding ? (
          <div className="flex min-w-0 items-center gap-2">
            <div className="min-w-0 flex-1">
              <AdGroupCombobox
                chosen={[]}
                disabled={disabled}
                fieldKey="entries"
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
          onCancel={cancel}
          onSelect={(key) => {
            if (key !== null) setChosen(key)
          }}
          onUndo={(key) => {
            restore(key)
          }}
          rowNoun={["ad group", "ad groups"]}
          rows={parents}
          selected={open?.entry.key ?? null}
        />
      </div>
      {open?.state === "cancelled" ? (
        <p className="text-muted-foreground flex flex-wrap items-center gap-2 text-sm">
          {open.name} is cancelled, so none of its{" "}
          {approvalCountLine(open.entry.keywords.length, "keyword")} will be added.
          <Button
            disabled={disabled}
            onClick={() => {
              restore(open.entry.key)
            }}
            size="sm"
            type="button"
            variant="outline"
          >
            Undo
          </Button>
        </p>
      ) : open ? (
        <DataTable
          key={open.entry.key}
          columns={columns}
          exportFilename="google-ads-new-keywords.csv"
          pageSize={25}
          renderCell={(column, row) => {
            const group = open
            const index = typeof row["index"] === "number" ? row["index"] : -1
            const keyword = group.entry.keywords[index]
            const locked = disabled || group.state !== "live"
            if (!keyword) return null
            if (column.key === "keyword") {
              const problem =
                group.state === "live" ? keywordProblem(checked, group.entry, keyword) : null
              return (
                <span className="grid min-w-0 gap-0.5 whitespace-normal">
                  <span className="text-sm wrap-anywhere">{keyword.text}</span>
                  {problem ? (
                    <span className="text-destructive text-xs wrap-anywhere">{problem}</span>
                  ) : null}
                </span>
              )
            }
            if (column.key === "match")
              return (
                <MatchTypeCell
                  disabled={locked}
                  keyword={keyword}
                  onChange={(matchType) => {
                    editKeyword(group, index, { matchType })
                  }}
                />
              )
            if (column.key === "bid")
              return acceptsBids(group) ? (
                <CommittedInput
                  ariaLabel={`Max CPC for ${keyword.text}`}
                  disabled={locked}
                  onCommit={(cpcBid) => {
                    editKeyword(group, index, { cpcBid: cpcBid.trim() })
                  }}
                  placeholder={group.bid}
                  value={keyword.cpcBid}
                />
              ) : (
                <span className="text-muted-foreground text-xs">Set by bidding</span>
              )
            if (column.key === "url")
              return (
                <CommittedInput
                  ariaLabel={`Final URL for ${keyword.text}`}
                  disabled={locked}
                  onCommit={(finalUrl) => {
                    editKeyword(group, index, { finalUrl: finalUrl.trim() })
                  }}
                  placeholder="Ad's URL"
                  value={keyword.finalUrl}
                />
              )
            if (column.key === "cancel" && group.state === "live")
              return (
                <Button
                  aria-label={`Cancel ${keyword.text}`}
                  disabled={disabled}
                  onClick={() => {
                    editKeywords(
                      group.entry.key,
                      group.entry.keywords.filter((_, at) => at !== index)
                    )
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
          rowDetails={false}
          rowNoun={["keyword", "keywords"]}
          rows={tableRows}
          searchable={tableRows.length >= TOOLS_FROM}
          summary={
            <NewKeyword
              disabled={disabled}
              onAdd={(pasted) => {
                addKeywords(open, pasted)
              }}
            />
          }
        />
      ) : null}
      {/* At the end, beside the approve button that waits on it. */}
      {keywordsNeedCheck(args, checked) && args.entries.length > 0 ? (
        <CheckChanges
          canCheck
          disabled={disabled}
          label={
            [...checked.checks.values()].some((check) => check.unavailable)
              ? "Check Again"
              : "Check Changes"
          }
          note="You changed these keywords, so Google needs to check them again."
          onCheck={controls.onReview}
          submitting={controls.submitting}
        />
      ) : null}
    </div>
  )
}

function parentRow(group: Group): ParentRow {
  return {
    cancelled: group.state === "cancelled",
    context: group.campaignName || null,
    key: group.entry.key,
    name: group.name,
    problems: group.state === "live" ? group.problems : 0,
    values: {
      bid: group.bid,
      keywords: group.entry.keywords.length,
      problems:
        group.state === "cancelled"
          ? "Cancelled"
          : group.state === "new"
            ? "No keywords yet"
            : group.problems > 0
              ? `${String(group.problems)} to fix`
              : "None",
    },
  }
}

/** One line to type a keyword and choose its match type; pasting several lines adds them all. */
function NewKeyword({
  disabled,
  onAdd,
}: {
  disabled: boolean
  onAdd: (keywords: PastedKeyword[]) => void
}) {
  const [text, setText] = useState("")
  const [matchType, setMatchType] = useState<KeywordMatchType>("PHRASE")
  // Plain text takes the chosen match type; [brackets] and "quotes" set their own.
  const read = (value: string) =>
    value.split(/\r?\n/).flatMap((line) => {
      const notated = /^\[.+\]$|^".+"$/.test(line.trim())
      return parseKeywordLines(line).map((keyword) =>
        notated ? keyword : { ...keyword, matchType }
      )
    })
  const submit = () => {
    const keywords = read(text)
    if (keywords.length === 0) return
    onAdd(keywords)
    setText("")
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Input
        aria-label="New keyword"
        className="min-w-56 flex-1 text-sm"
        disabled={disabled}
        onChange={(event) => {
          setText(event.currentTarget.value)
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault()
            submit()
          }
        }}
        onPaste={(event: ClipboardEvent<HTMLInputElement>) => {
          const pasted = event.clipboardData.getData("text")
          if (!pasted.includes("\n")) return
          event.preventDefault()
          onAdd(read(pasted))
        }}
        placeholder="Type a keyword, or paste several, one per line"
        value={text}
      />
      <SegmentedChoice
        ariaLabel="Match type for the new keyword"
        compact
        disabled={disabled}
        onChange={setMatchType}
        options={MATCH_OPTIONS}
        value={matchType}
      />
      <Button
        disabled={disabled || read(text).length === 0}
        onClick={submit}
        size="sm"
        type="button"
        variant="outline"
      >
        <PlusIcon aria-hidden="true" />
        Add Keyword
      </Button>
    </div>
  )
}

function sameKeyword(keyword: PastedKeyword): string {
  return `${keyword.matchType}/${keyword.text.toLowerCase()}`
}

function parkedEntries(value: unknown): KeywordEntry[] {
  return Array.isArray(value) ? (parseCreateKeywordsArgs({ entries: value })?.entries ?? []) : []
}
