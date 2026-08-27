// apps/web/src/integrations/notion/components/read-results.tsx

import type { ReactNode } from "react"

import { MarkdownContent } from "@/components/markdown/markdown-content"
import type { FanOutEntry } from "@/components/tool-ui/fan-out"
import { FanOutShell, FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { Badge } from "@/components/ui/badge"
import { DataTable } from "@/components/ui/data-table"
import { NotionLogo } from "@/integrations/notion/components/logo"
import {
  displayNotionValue,
  type NotionPageData,
  type NotionQueryData,
  type NotionSearchData,
  type NotionSearchItem,
} from "@/integrations/notion/lib/read-results"
import { formatDateTime, humanizeKey } from "@/lib/format"

export function NotionFanOut({
  children,
  defaultOpen,
  entries,
  title,
}: {
  children: (entry: FanOutEntry, index: number) => ReactNode
  defaultOpen: boolean
  entries: FanOutEntry[]
  title: string
}) {
  return (
    <div aria-label={`${title} results`} className="w-full min-w-0">
      <FanOutShell
        contextLabel="Workspace"
        defaultOpen={defaultOpen}
        entries={entries}
        emptyLabel="No Notion workspaces were queried."
        externalLabel="Workspace ID"
        heading={<NotionHeading>{title}</NotionHeading>}
      >
        {children}
      </FanOutShell>
    </div>
  )
}

export function NotionSkeleton({ label, title }: { label: string; title: string }) {
  return <FanOutSkeleton heading={<NotionHeading>{title}</NotionHeading>} label={label} />
}

export function NotionSearchResult({ data }: { data: NotionSearchData }) {
  return (
    <div className="grid gap-3">
      <p className="text-muted-foreground text-xs">{data.coverageNote}</p>
      {data.items.length === 0 ? (
        <EmptyState>No matching pages or data sources were found.</EmptyState>
      ) : (
        <div className="grid gap-2">
          {data.items.map((item, index) => (
            <NotionItem item={item} key={`${item.kind}:${item.url}:${String(index)}`} />
          ))}
        </div>
      )}
      {data.hasMore ? (
        <p className="text-muted-foreground text-xs">More title matches are available.</p>
      ) : null}
      <UnknownFields
        known={new Set(["items", "count", "has_more", "next_cursor", "coverage_note"])}
        value={data.raw}
      />
    </div>
  )
}

export function NotionPageResult({ data }: { data: NotionPageData }) {
  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <ResultLink label={data.title} url={data.url} />
        {data.truncated ? <Badge variant="warning">64 KiB limit reached</Badge> : null}
        {data.providerTruncated ? <Badge variant="warning">Notion result incomplete</Badge> : null}
      </div>
      <div className="border-border bg-muted/20 max-h-96 overflow-auto rounded-lg border p-3">
        <MarkdownContent content={data.markdown} />
      </div>
      <dl className="grid gap-2 text-xs sm:grid-cols-2">
        <Detail label="Last edited" value={formatDateTime(data.sourceUpdatedAt)} />
        <Detail label="Bytes returned" value={String(data.bytesReturned)} />
        <Detail label="Unknown blocks" value={String(data.unknownBlockCount)} />
      </dl>
      <UnknownFields
        known={
          new Set([
            "reference",
            "title",
            "markdown",
            "url",
            "source_updated_at",
            "bytes_returned",
            "truncated",
            "provider_truncated",
            "unknown_block_count",
          ])
        }
        value={data.raw}
      />
    </div>
  )
}

export function NotionQueryResult({ data }: { data: NotionQueryData }) {
  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap gap-2">
        {data.incomplete ? <Badge variant="warning">Query incomplete</Badge> : null}
        {data.propertiesTruncated ? (
          <Badge variant="warning">Some record properties omitted</Badge>
        ) : null}
        {data.hasMore ? <Badge variant="secondary">More records available</Badge> : null}
      </div>
      {data.rows.length === 0 ? (
        <EmptyState>No records were returned.</EmptyState>
      ) : (
        <DataTable
          columns={data.columns}
          exportFilename="notion-data-source-records.csv"
          pageSize={25}
          rows={data.rows}
        />
      )}
      <UnknownFields
        known={new Set(["records", "count", "has_more", "next_cursor", "incomplete"])}
        value={data.raw}
      />
    </div>
  )
}

function NotionHeading({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <NotionLogo aria-hidden="true" className="size-4 shrink-0" />
      <span className="truncate">{children}</span>
    </span>
  )
}

function NotionItem({ item }: { item: NotionSearchItem }) {
  return (
    <article className="border-border bg-muted/20 grid gap-1 rounded-lg border px-3 py-2">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <ResultLink label={item.title} url={item.url} />
        <Badge variant="secondary">{item.kind === "page" ? "Page" : "Data source"}</Badge>
      </div>
      <p className="text-muted-foreground text-xs">
        Updated <time dateTime={item.lastEditedTime}>{formatDateTime(item.lastEditedTime)}</time>
      </p>
      <UnknownFields
        known={new Set(["kind", "title", "url", "last_edited_time", "reference"])}
        value={item.raw}
      />
    </article>
  )
}

function ResultLink({ label, url }: { label: string; url: string }) {
  return url.startsWith("https://") ? (
    <a
      className="text-link hover:text-primary min-w-0 font-medium underline underline-offset-2"
      href={url}
      rel="noreferrer"
      target="_blank"
    >
      {label}
    </a>
  ) : (
    <span className="min-w-0 font-medium">{label}</span>
  )
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid min-w-0 gap-0.5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 wrap-break-word whitespace-pre-wrap">{value}</dd>
    </div>
  )
}

function UnknownFields({ known, value }: { known: Set<string>; value: Record<string, unknown> }) {
  const entries = Object.entries(value).filter(([key]) => !known.has(key))
  if (entries.length === 0) {
    return null
  }
  return (
    <dl className="border-border grid gap-2 border-t pt-2 text-xs sm:grid-cols-2">
      {entries.map(([key, item]) => (
        <Detail key={key} label={humanizeKey(key)} value={displayNotionValue(item)} />
      ))}
    </dl>
  )
}

function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="border-border bg-muted/20 rounded-lg border border-dashed px-3 py-5 text-center">
      <p className="text-muted-foreground text-sm">{children}</p>
    </div>
  )
}
