// apps/web/src/features/conversations/components/memory-tool-row.tsx

import { useState } from "react"
import { BrainIcon } from "lucide-react"

import { approvalFallbackFields } from "@/components/tool-ui/approval-fallback-fields"
import { FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { ToolResultCard, type ToolResultDetail } from "@/components/tool-ui/result-card"
import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-card"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ApprovalDecisionBlock } from "@/features/conversations/components/approval-decision-block"
import { ActivityStatusBadge } from "@/features/conversations/components/tool-activity-status"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  FORGET_MEMORY_TOOL_NAME,
  SAVE_MEMORY_TOOL_NAME,
  SEARCH_MEMORY_TOOL_NAME,
  UPDATE_MEMORY_TOOL_NAME,
  type MemorySearchToolHit,
  type MemoryToolSummary,
  forgetMemoryResult,
  saveMemoryResult,
  saveMemoryTitleArg,
  searchMemoryQueryArg,
  searchMemoryResult,
  updateMemoryResult,
} from "@/features/conversations/native-tools/memory-tools"
import { formatMemoryConfidence } from "@/features/memories/components/memory-display"
import type { ToolUi } from "@/features/tools/types"
import { plainTextPreview, pluralize, titleCaseToken } from "@/lib/format"
import { isRecord } from "@/lib/guards"

type MemoryToolRowProps = {
  activity: ToolActivity
  approvalDecision?: ToolApprovalDecisionControls
  defaultOpen: boolean
  label?: string
  ui?: ToolUi | null
}

export function MemoryToolRow({
  activity,
  approvalDecision,
  defaultOpen,
  label = "Save Memory",
  ui = null,
}: MemoryToolRowProps) {
  if (
    activity.status === "awaiting_approval" &&
    activity.name === SAVE_MEMORY_TOOL_NAME &&
    approvalDecision
  ) {
    const fields = ui?.arg_fields ?? []
    const args = isRecord(activity.args) ? activity.args : {}
    const kind = typeof args["kind"] === "string" ? args["kind"] : null
    const scope = typeof args["scope"] === "string" ? args["scope"] : null
    return (
      <ApprovalDecisionBlock
        activity={activity}
        controls={approvalDecision}
        fallbackFields={approvalFallbackFields(activity.args, fields)}
        fields={fields}
        iconToken={ui?.icon ?? "book"}
        label={label}
        prompt="The agent wants to save trusted memory that can shape future responses."
        title={ui?.approval_title ?? "Save Memory"}
      >
        <div className="flex flex-wrap gap-2">
          {kind ? (
            <Badge variant={kind === "core" ? "warning" : "secondary"}>
              {titleCaseToken(kind, "Memory")}
            </Badge>
          ) : null}
          {scope ? <Badge variant="outline">{titleCaseToken(scope, "Scope")} scope</Badge> : null}
        </div>
      </ApprovalDecisionBlock>
    )
  }
  if (activity.status === "running" || activity.status === "awaiting_approval") {
    const state = memoryPendingState(activity)
    return state ? (
      <FanOutSkeleton
        heading={<MemoryToolHeading>{state.heading}</MemoryToolHeading>}
        label={activity.status === "running" ? state.runningLabel : state.waitingLabel}
        {...(state.summary ? { summary: state.summary } : {})}
      />
    ) : null
  }
  if (
    activity.status === "failed" ||
    activity.status === "denied" ||
    activity.status === "unknown"
  ) {
    return <MemoryFailureRow activity={activity} />
  }
  if (activity.name === SAVE_MEMORY_TOOL_NAME) {
    return <SaveMemoryRow activity={activity} defaultOpen={defaultOpen} />
  }
  if (activity.name === SEARCH_MEMORY_TOOL_NAME) {
    return <SearchMemoryRow activity={activity} defaultOpen={defaultOpen} />
  }
  if (activity.name === UPDATE_MEMORY_TOOL_NAME) {
    return <UpdateMemoryRow activity={activity} defaultOpen={defaultOpen} />
  }
  if (activity.name === FORGET_MEMORY_TOOL_NAME) {
    return <ForgetMemoryRow activity={activity} defaultOpen={defaultOpen} />
  }
  return null
}

const VISIBLE_MATCH_LIMIT = 5

function SaveMemoryRow({ activity, defaultOpen }: MemoryToolRowProps) {
  const result = saveMemoryResult(activity.result)
  if (!result) {
    return null
  }

  if (result.status === "near_duplicate") {
    return (
      <ToolResultCard
        ariaLabel="Memory not saved because a similar memory exists"
        defaultOpen={defaultOpen}
        details={[
          ...(result.existing_memory ? memoryDetailEntries(result.existing_memory) : []),
          { label: "Similarity", summary: false, value: formatMemoryConfidence(result.similarity) },
        ]}
        heading={<MemoryToolHeading>Save Memory</MemoryToolHeading>}
        trailing={<Badge variant="warning">Not Saved</Badge>}
      >
        <div className="grid min-w-0 gap-2">
          <p className="text-muted-foreground text-sm">
            A very similar memory already exists ({formatMemoryConfidence(result.similarity)}{" "}
            similar), so nothing new was saved.
          </p>
          {result.existing_memory ? <MemorySummaryLine memory={result.existing_memory} /> : null}
        </div>
      </ToolResultCard>
    )
  }

  return (
    <ToolResultCard
      ariaLabel={`Saved memory ${result.memory.title}`}
      defaultOpen={defaultOpen}
      details={[
        ...memoryDetailEntries(result.memory),
        ...(result.similarity !== null
          ? [
              {
                label: "Similarity",
                summary: false,
                value: formatMemoryConfidence(result.similarity),
              },
            ]
          : []),
      ]}
      heading={<MemoryToolHeading>Save Memory</MemoryToolHeading>}
      trailing={
        <Badge variant="success">{result.status === "reinforced" ? "Reinforced" : "Saved"}</Badge>
      }
    >
      <div className="grid min-w-0 gap-2">
        <MemorySummaryLine memory={result.memory} />
        {result.status === "reinforced" ? (
          <p className="text-muted-foreground text-xs">
            This matched an existing memory, which was strengthened instead of duplicated.
          </p>
        ) : null}
      </div>
    </ToolResultCard>
  )
}

function SearchMemoryRow({ activity, defaultOpen }: MemoryToolRowProps) {
  const [showAll, setShowAll] = useState(false)
  const result = searchMemoryResult(activity.result)
  if (!result) {
    return null
  }

  const countLabel = `${String(result.total)} ${pluralize(result.total, "Match", "Matches")}`
  const visibleHits = showAll ? result.results : result.results.slice(0, VISIBLE_MATCH_LIMIT)
  const hiddenCount = result.results.length - visibleHits.length
  return (
    <ToolResultCard
      ariaLabel={`Memory search results for ${result.query}`}
      defaultOpen={defaultOpen}
      details={[
        { label: "Search", value: result.query },
        { label: "Matches", value: String(result.total) },
        ...(result.used_lexical_fallback
          ? [{ label: "Mode", summary: false, value: "Keyword matches only" }]
          : []),
      ]}
      heading={<MemoryToolHeading>Search Memory</MemoryToolHeading>}
      trailing={<Badge variant="success">{countLabel}</Badge>}
    >
      <div className="grid min-w-0 gap-2">
        {result.matches_found > result.total ? (
          <p className="text-muted-foreground text-xs">
            Showing the top {String(result.total)} of {String(result.matches_found)} matches.
          </p>
        ) : null}
        {result.results_truncated ? (
          <p className="text-muted-foreground text-xs">Some match content was shortened to fit.</p>
        ) : null}
        {result.results.length > 0 ? (
          <ol
            aria-label="Memory matches"
            className="divide-border divide-y overflow-hidden rounded-lg border"
          >
            {visibleHits.map((hit, index) => (
              <MemoryHitItem hit={hit} key={`${hit.id}:${String(index)}`} rank={index + 1} />
            ))}
          </ol>
        ) : (
          <p className="text-muted-foreground px-4 py-6 text-center text-sm">
            No matching memories were found.
          </p>
        )}
        {hiddenCount > 0 || showAll ? (
          <Button
            className="justify-self-start"
            onClick={() => {
              setShowAll((current) => !current)
            }}
            size="sm"
            type="button"
            variant="ghost"
          >
            {showAll
              ? "Show Fewer"
              : `Show All ${String(result.results.length)} ${pluralize(result.results.length, "Match", "Matches")}`}
          </Button>
        ) : null}
      </div>
    </ToolResultCard>
  )
}

function MemoryHitItem({ hit, rank }: { hit: MemorySearchToolHit; rank: number }) {
  const preview = plainTextPreview(hit.content)
  return (
    <li className="flex min-w-0 flex-col gap-1 px-3 py-2">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <span className="min-w-0 truncate text-sm font-medium">{hit.title}</span>
        <MemoryScopeBadge scope={hit.scope} />
        <MemoryKindBadge kind={hit.kind} />
        {rank === 1 ? (
          <span
            className="text-muted-foreground ml-auto text-xs"
            title="Results are ordered by combined keyword and meaning relevance."
          >
            Best match
          </span>
        ) : null}
      </div>
      {preview ? (
        <p className="text-muted-foreground line-clamp-2 text-sm whitespace-pre-line">{preview}</p>
      ) : null}
    </li>
  )
}

function UpdateMemoryRow({ activity, defaultOpen }: MemoryToolRowProps) {
  const result = updateMemoryResult(activity.result)
  if (!result) {
    return null
  }

  return (
    <ToolResultCard
      ariaLabel={`Updated memory ${result.memory.title}`}
      defaultOpen={defaultOpen}
      details={memoryDetailEntries(result.memory)}
      heading={<MemoryToolHeading>Update Memory</MemoryToolHeading>}
      trailing={<Badge variant="success">Updated</Badge>}
    >
      <div className="grid min-w-0 gap-2">
        <MemorySummaryLine memory={result.memory} />
        {result.status === "superseded" ? (
          <p className="text-muted-foreground text-xs">
            The content changed, so the previous version was kept in history.
          </p>
        ) : null}
      </div>
    </ToolResultCard>
  )
}

function ForgetMemoryRow({ activity, defaultOpen }: MemoryToolRowProps) {
  const result = forgetMemoryResult(activity.result)
  if (!result) {
    return null
  }

  return (
    <ToolResultCard
      ariaLabel={`Archived memory ${result.memory.title}`}
      defaultOpen={defaultOpen}
      details={memoryDetailEntries(result.memory)}
      heading={<MemoryToolHeading>Forget Memory</MemoryToolHeading>}
      trailing={<Badge variant="secondary">Archived</Badge>}
    >
      <div className="grid min-w-0 gap-2">
        <MemorySummaryLine memory={result.memory} />
        <p className="text-muted-foreground text-xs">
          {result.status === "already_archived"
            ? "This memory was already archived."
            : "This memory was archived and will no longer be used."}
        </p>
      </div>
    </ToolResultCard>
  )
}

function MemoryFailureRow({ activity }: Pick<MemoryToolRowProps, "activity">) {
  const state = memoryPendingState(activity)
  if (!state) {
    return null
  }
  const message =
    typeof activity.result === "string" && activity.result.trim()
      ? activity.result
      : activity.status === "denied"
        ? "This memory action was declined. Nothing was changed."
        : "The memory action did not finish. No change was confirmed."
  return (
    <ToolResultCard
      ariaLabel={`${state.heading} failed`}
      defaultOpen
      details={[{ label: "Action", value: state.heading }]}
      heading={<MemoryToolHeading>{state.heading}</MemoryToolHeading>}
      trailing={<ActivityStatusBadge status={activity.status} />}
    >
      <Alert variant="destructive">
        <AlertTitle>
          {activity.status === "denied" ? "Action Declined" : "What Went Wrong"}
        </AlertTitle>
        <AlertDescription className="whitespace-pre-wrap">{message}</AlertDescription>
      </Alert>
    </ToolResultCard>
  )
}

function MemorySummaryLine({ memory }: { memory: MemoryToolSummary }) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2">
      <span className="min-w-0 truncate text-sm font-medium">{memory.title}</span>
      <MemoryScopeBadge scope={memory.scope} />
      <MemoryKindBadge kind={memory.kind} />
      <span className="text-muted-foreground text-xs">
        {titleCaseToken(memory.memory_type, "Memory")}
      </span>
    </div>
  )
}

function MemoryScopeBadge({ scope }: { scope: MemoryToolSummary["scope"] }) {
  return <Badge variant="outline">{memoryToolScopeLabel(scope)}</Badge>
}

function MemoryKindBadge({ kind }: { kind: MemoryToolSummary["kind"] }) {
  return (
    <Badge variant={kind === "core" ? "warning" : "secondary"}>
      {titleCaseToken(kind, "Memory")}
    </Badge>
  )
}

function MemoryToolHeading({ children }: { children: string }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <BrainIcon className="text-muted-foreground size-4 shrink-0" />
      <span className="truncate">{children}</span>
    </span>
  )
}

function memoryDetailEntries(memory: MemoryToolSummary): ToolResultDetail[] {
  return [
    { label: "Memory", value: memory.title },
    { label: "Scope", summary: false, value: memoryToolScopeLabel(memory.scope) },
    { label: "Kind", summary: false, value: titleCaseToken(memory.kind, "Memory") },
    { label: "Type", summary: false, value: titleCaseToken(memory.memory_type, "Memory") },
    { label: "Importance", summary: false, value: `${String(memory.importance)} of 5` },
  ]
}

function memoryToolScopeLabel(scope: MemoryToolSummary["scope"]) {
  return scope === "user" ? "Personal" : titleCaseToken(scope, "Scope")
}

function memoryPendingState(activity: ToolActivity) {
  if (activity.name === SAVE_MEMORY_TOOL_NAME) {
    const title = saveMemoryTitleArg(activity.args)
    return {
      heading: "Save Memory",
      runningLabel: title ? `Saving memory ${title}…` : "Saving memory…",
      summary: title,
      waitingLabel: "Waiting for approval to save this memory…",
    }
  }
  if (activity.name === SEARCH_MEMORY_TOOL_NAME) {
    const query = searchMemoryQueryArg(activity.args)
    return {
      heading: "Search Memory",
      runningLabel: query ? `Searching memory for ${query}…` : "Searching memory…",
      summary: query,
      waitingLabel: "Waiting to search memory…",
    }
  }
  if (activity.name === UPDATE_MEMORY_TOOL_NAME) {
    return {
      heading: "Update Memory",
      runningLabel: "Updating memory…",
      summary: null,
      waitingLabel: "Waiting for approval to update this memory…",
    }
  }
  if (activity.name === FORGET_MEMORY_TOOL_NAME) {
    return {
      heading: "Forget Memory",
      runningLabel: "Forgetting memory…",
      summary: null,
      waitingLabel: "Waiting to forget this memory…",
    }
  }
  return null
}
