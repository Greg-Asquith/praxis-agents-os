// apps/web/src/features/conversations/components/kb-tool-row.tsx

import { useState } from "react"
import { Link } from "@tanstack/react-router"
import { BookOpenIcon, LibraryIcon, LockIcon, type LucideIcon } from "lucide-react"

import { FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { ToolResultCard } from "@/components/tool-ui/result-card"
import { ExternalContent } from "@/components/tool-ui/external-content"
import { isUntrustedNode } from "@/components/tool-ui/untrusted-node"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { MessageMarkdown } from "@/features/conversations/components/message-markdown"
import { ActivityStatusBadge } from "@/features/conversations/components/tool-activity-status"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  READ_DOCUMENT_TOOL_NAME,
  SEARCH_KNOWLEDGE_TOOL_NAME,
  type KnowledgeSearchHit,
  knowledgeChunkPreview,
  readDocumentResult,
  searchKnowledgeQueryArg,
  searchKnowledgeResult,
} from "@/features/conversations/native-tools/kb-tools"
import { SourceTypeBadge } from "@/features/knowledge/components/source-type-badge"
import { pluralize } from "@/lib/format"

type KbToolRowProps = {
  activity: ToolActivity
  defaultOpen: boolean
}

export function KbToolRow({ activity, defaultOpen }: KbToolRowProps) {
  if (activity.status === "running" || activity.status === "awaiting_approval") {
    const state = kbPendingState(activity)
    return state ? (
      <FanOutSkeleton
        heading={<KbToolHeading icon={state.icon}>{state.heading}</KbToolHeading>}
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
    return <KbFailureRow activity={activity} />
  }
  if (activity.name === SEARCH_KNOWLEDGE_TOOL_NAME) {
    return <SearchKnowledgeRow activity={activity} defaultOpen={defaultOpen} />
  }
  if (activity.name === READ_DOCUMENT_TOOL_NAME) {
    return <ReadDocumentRow activity={activity} defaultOpen={defaultOpen} />
  }
  return null
}

const VISIBLE_MATCH_LIMIT = 5

function SearchKnowledgeRow({ activity, defaultOpen }: KbToolRowProps) {
  const [showAll, setShowAll] = useState(false)
  const result = searchKnowledgeResult(activity.result)
  if (!result) {
    return null
  }

  const countLabel = `${String(result.total)} ${pluralize(result.total, "Match", "Matches")}`
  const visibleHits = showAll ? result.results : result.results.slice(0, VISIBLE_MATCH_LIMIT)
  const hiddenCount = result.results.length - visibleHits.length
  return (
    <ToolResultCard
      ariaLabel={`Knowledge search results for ${result.query}`}
      defaultOpen={defaultOpen}
      details={[
        { label: "Search", value: result.query },
        { label: "Matches", value: String(result.total) },
        ...(result.used_lexical_fallback
          ? [{ label: "Mode", summary: false, value: "Keyword matches only" }]
          : []),
      ]}
      heading={<KbToolHeading icon={LibraryIcon}>Search Knowledge</KbToolHeading>}
      trailing={<Badge variant="success">{countLabel}</Badge>}
    >
      <div className="grid min-w-0 gap-2">
        {result.used_lexical_fallback ? (
          <p className="text-muted-foreground text-xs">
            Showing keyword matches while documents finish processing.
          </p>
        ) : null}
        {result.results.length > 0 ? (
          <ol
            aria-label="Knowledge matches"
            className="divide-border divide-y overflow-hidden rounded-lg border"
          >
            {visibleHits.map((hit, index) => (
              <KnowledgeHitItem
                hit={hit}
                key={`${hit.document_id}:${String(index)}`}
                rank={index + 1}
              />
            ))}
          </ol>
        ) : (
          <p className="text-muted-foreground px-4 py-6 text-center text-sm">
            No matching knowledge was found.
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

function KnowledgeHitItem({ hit, rank }: { hit: KnowledgeSearchHit; rank: number }) {
  const preview = knowledgeChunkPreview(hit.content)
  return (
    <li className="flex min-w-0 flex-col gap-1 px-3 py-2">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <KnowledgeDocumentLink documentId={hit.document_id} title={hit.document_title} />
        <SourceTypeBadge sourceType={hit.source_type} />
        {hit.is_private ? <PrivateTag /> : null}
        {rank === 1 ? (
          <span
            className="text-muted-foreground ml-auto text-xs"
            title="Results are ordered by combined keyword and meaning relevance."
          >
            Best match
          </span>
        ) : null}
      </div>
      {preview ? <p className="text-muted-foreground line-clamp-2 text-sm">{preview}</p> : null}
    </li>
  )
}

function ReadDocumentRow({ activity, defaultOpen }: KbToolRowProps) {
  const result = readDocumentResult(activity.result)
  if (!result) {
    return null
  }

  const charsRead = result.end - result.start
  const isPartial = charsRead < result.total_chars
  return (
    <ToolResultCard
      ariaLabel={`Knowledge document ${result.title}`}
      defaultOpen={defaultOpen}
      details={[
        { label: "Document", value: result.title },
        {
          label: "Read",
          value: `${charsRead.toLocaleString()} of ${result.total_chars.toLocaleString()} characters`,
        },
      ]}
      heading={<KbToolHeading icon={BookOpenIcon}>Read Knowledge Document</KbToolHeading>}
      trailing={<ActivityStatusBadge status={activity.status} />}
    >
      <div className="grid min-w-0 gap-3">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <KnowledgeDocumentLink documentId={result.document_id} title={result.title} />
          <SourceTypeBadge sourceType={result.source_type} />
          {result.is_private ? <PrivateTag /> : null}
        </div>
        {isPartial ? (
          <p className="text-muted-foreground text-xs">
            Showing part of this document ({charsRead.toLocaleString()} of{" "}
            {result.total_chars.toLocaleString()} characters).
          </p>
        ) : null}
        {isUntrustedNode(result.content) ? (
          <ExternalContent label="Knowledge document content" value={result.content} />
        ) : (
          <div className="border-border/70 overflow-hidden rounded-lg border">
            <p className="bg-muted/25 border-b px-3 py-2 text-xs font-medium">Content</p>
            <div className="max-h-96 min-w-0 overflow-auto px-3 py-2">
              <MessageMarkdown content={result.content} />
            </div>
          </div>
        )}
      </div>
    </ToolResultCard>
  )
}

function KbFailureRow({ activity }: Pick<KbToolRowProps, "activity">) {
  const state = kbPendingState(activity)
  if (!state) {
    return null
  }
  const message =
    typeof activity.result === "string" && activity.result.trim()
      ? activity.result
      : activity.status === "denied"
        ? "This knowledge lookup was declined. Nothing was read."
        : "The knowledge lookup did not finish. No result was confirmed."
  return (
    <ToolResultCard
      ariaLabel={`${state.heading} failed`}
      defaultOpen
      details={[{ label: "Action", value: state.heading }]}
      heading={<KbToolHeading icon={state.icon}>{state.heading}</KbToolHeading>}
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

function KnowledgeDocumentLink({ documentId, title }: { documentId: string; title: string }) {
  return (
    <Link
      className="min-w-0 truncate text-sm font-medium hover:underline"
      params={{ documentId }}
      to="/knowledge/$documentId"
    >
      {title}
    </Link>
  )
}

function PrivateTag() {
  return (
    <span className="text-muted-foreground inline-flex items-center gap-1 text-xs">
      <LockIcon className="size-3" />
      Private
    </span>
  )
}

function KbToolHeading({ children, icon: Icon }: { children: string; icon: LucideIcon }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <Icon className="text-muted-foreground size-4 shrink-0" />
      <span className="truncate">{children}</span>
    </span>
  )
}

function kbPendingState(activity: ToolActivity) {
  if (activity.name === SEARCH_KNOWLEDGE_TOOL_NAME) {
    const query = searchKnowledgeQueryArg(activity.args)
    return {
      heading: "Search Knowledge",
      icon: LibraryIcon,
      runningLabel: query ? `Searching knowledge for ${query}…` : "Searching knowledge…",
      summary: query,
      waitingLabel: "Waiting to search knowledge…",
    }
  }
  if (activity.name === READ_DOCUMENT_TOOL_NAME) {
    return {
      heading: "Read Knowledge Document",
      icon: BookOpenIcon,
      runningLabel: "Reading knowledge document…",
      summary: null,
      waitingLabel: "Waiting to read knowledge document…",
    }
  }
  return null
}
