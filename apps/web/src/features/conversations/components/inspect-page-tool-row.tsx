// apps/web/src/features/conversations/components/inspect-page-tool-row.tsx

import {
  ChevronRightIcon,
  CircleCheckIcon,
  DotIcon,
  ScanSearchIcon,
  TriangleAlertIcon,
} from "lucide-react"
import { useMemo, type ReactNode } from "react"

import { DetailList, type DetailItem } from "@/components/tool-ui/detail-list"
import { FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { parseResultPreview } from "@/components/tool-ui/result-preview"
import { ResultPreviewNotice } from "@/components/tool-ui/result-preview-notice"
import { ToolResultCard } from "@/components/tool-ui/result-card"
import { RetainedResult } from "@/components/tool-ui/retained-result"
import { ToolHeading } from "@/components/tool-ui/tool-heading"
import { Badge } from "@/components/ui/badge"
import { DataTable, type DataColumn, type DataTableTab } from "@/components/ui/data-table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  type InspectPageResult,
  type InspectedPage,
  type InspectedRobots,
  type InspectedSitemap,
  type PageMeta,
  type StructuredDataBlock,
  inspectPageArgsUrl,
  inspectPageResult,
} from "@/features/conversations/components/inspect-page-result"
import { pageChecks } from "@/features/conversations/components/inspect-page-checks"
import { RedirectList } from "@/features/conversations/components/redirect-list"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { formatDateTime, titleCaseToken } from "@/lib/format"
import { cn } from "@/lib/utils"

const HEADING = <ToolHeading icon={ScanSearchIcon}>Inspect Page</ToolHeading>

const KIND_LABELS = {
  page: "Page",
  robots: "robots.txt",
  sitemap: "Sitemap",
  unsupported: "Not Inspected",
} as const

export function InspectPageToolRow({
  activity,
  defaultOpen = false,
}: {
  activity: ToolActivity
  defaultOpen?: boolean
}) {
  if (activity.status === "running") {
    const url = inspectPageArgsUrl(activity.args)
    return url ? (
      <FanOutSkeleton
        running
        heading={HEADING}
        label={`Inspecting ${url}…`}
        summary={`URL: ${url}`}
      />
    ) : null
  }
  if (activity.status !== "completed") return null
  const envelope = parseResultPreview(activity.result)
  const data = envelope?.data ?? activity.result
  if (inspectPageResult(data) === null) return null
  const render = (visible: unknown, _incomplete: boolean, control?: ReactNode) => {
    const result = inspectPageResult(visible)
    return result ? (
      <InspectPageCard
        defaultOpen={defaultOpen}
        notice={
          envelope ? (
            <>
              {control}
              <ResultPreviewNotice data={visible} preview={envelope} />
            </>
          ) : null
        }
        result={result}
      />
    ) : null
  }
  return envelope ? (
    <RetainedResult
      key={envelope.fileId}
      preview={envelope}
      validate={(value) => inspectPageResult(value) !== null}
    >
      {render}
    </RetainedResult>
  ) : (
    render(data, false)
  )
}

function InspectPageCard({
  defaultOpen,
  notice,
  result,
}: {
  defaultOpen: boolean
  notice: ReactNode
  result: InspectPageResult
}) {
  const details = [
    { label: "URL", value: result.finalUrl },
    { label: "Status", value: String(result.status) },
    { label: "Fetched", value: formatDateTime(result.fetchedAt) },
  ]
  if (result.kind) details.splice(2, 0, { label: "Type", value: KIND_LABELS[result.kind] })
  if (result.sitemap) {
    const label = result.sitemap.index ? "Child Sitemaps" : "Pages"
    details.push({ label, value: result.sitemap.total.toLocaleString("en-GB") })
  }
  if (result.robots) {
    details.push({ label: "Sitemaps", value: String(result.robots.sitemaps.length) })
  }
  return (
    <ToolResultCard
      ariaLabel={`Inspected ${result.finalUrl}`}
      defaultOpen={defaultOpen}
      details={details}
      heading={HEADING}
      trailing={<StatusBadge result={result} />}
    >
      <div className="grid min-w-0 gap-4">
        {notice}
        {result.note ? <p className="text-muted-foreground text-xs">{result.note}</p> : null}
        <RedirectList redirects={result.redirects} />
        {result.page ? <PageFacts finalUrl={result.finalUrl} page={result.page} /> : null}
        {result.sitemap ? <SitemapEntries sitemap={result.sitemap} /> : null}
        {result.robots ? <RobotsRules robots={result.robots} /> : null}
      </div>
    </ToolResultCard>
  )
}

function StatusBadge({ result }: { result: InspectPageResult }) {
  if (result.blockedBySite) return <Badge variant="warning">Blocked by Site</Badge>
  if (result.status < 200 || result.status >= 300) {
    return <Badge variant="destructive">Status {result.status}</Badge>
  }
  if (result.page?.looksClientRendered) return <Badge variant="warning">Needs a Browser</Badge>
  if (result.kind === "unsupported") return <Badge variant="secondary">Not Inspected</Badge>
  return <Badge variant="success">Done</Badge>
}

const CHECK_ICONS = {
  info: { className: "text-muted-foreground", icon: DotIcon },
  pass: { className: "text-success", icon: CircleCheckIcon },
  warning: { className: "text-warning", icon: TriangleAlertIcon },
}

function PageFacts({ finalUrl, page }: { finalUrl: string; page: InspectedPage }) {
  const checks = pageChecks(page, finalUrl)
  return (
    <>
      <ul aria-label="Checks" className="grid gap-x-6 gap-y-1.5 text-xs sm:grid-cols-2">
        {checks.map((check) => {
          const { className, icon: Icon } = CHECK_ICONS[check.tone]
          return (
            <li className="flex min-w-0 items-start gap-1.5" key={check.label}>
              <Icon aria-hidden="true" className={cn("mt-px size-3.5 shrink-0", className)} />
              <span className="min-w-0 wrap-break-word">{check.label}</span>
            </li>
          )
        })}
      </ul>
      {page.meta ? <DetailList className="border-t pt-3" items={metaItems(page.meta)} /> : null}
      <PageTables page={page} />
    </>
  )
}

const META_LABELS: [keyof PageMeta, string][] = [
  ["title", "Title"],
  ["description", "Description"],
  ["canonical", "Canonical"],
  ["robots", "Robots"],
  ["language", "Language"],
  ["viewport", "Viewport"],
  ["metaRefresh", "Meta Refresh"],
]

// Title and description always show, so a missing one is visible; other fields show when set.
function metaItems(meta: PageMeta): DetailItem[] {
  return META_LABELS.flatMap(([key, label]): DetailItem[] => {
    const value = meta[key]
    if (value) return [{ label, value }]
    return key === "title" || key === "description"
      ? [{ label, value: <span className="text-muted-foreground">None</span> }]
      : []
  })
}

const TAG_COLUMNS: DataColumn[] = [
  { key: "vendor", kind: "text", label: "Tag", width: "auto" },
  { key: "category", kind: "text", label: "Type", width: 140 },
  { key: "id", kind: "id", label: "ID" },
  { key: "found_in", kind: "text", label: "Found In", width: 140 },
]

const LINK_COLUMNS: DataColumn[] = [
  { key: "text", kind: "text", label: "Link Text", width: 220 },
  { key: "url", kind: "link", label: "Goes To", width: "auto" },
  { key: "scope", kind: "text", label: "Type", width: 170 },
]

const LINK_TABS: DataTableTab[] = [
  { id: "all", label: "All", match: () => true },
  {
    hideWhenEmpty: true,
    id: "internal",
    label: "Internal",
    match: (row) => row["internal"] === true,
  },
  {
    hideWhenEmpty: true,
    id: "external",
    label: "External",
    match: (row) => row["internal"] === false,
  },
  {
    hideWhenEmpty: true,
    id: "nofollow",
    label: "Nofollow",
    match: (row) => row["nofollow"] === true,
  },
]

const IMAGE_COLUMNS: DataColumn[] = [
  { key: "alt", kind: "text", label: "Alt Text", width: 280 },
  { key: "src", kind: "link", label: "Image", width: "auto" },
]

const IMAGE_TABS: DataTableTab[] = [
  { id: "all", label: "All", match: () => true },
  {
    hideWhenEmpty: true,
    id: "missing",
    label: "Missing Alt Text",
    match: (row) => row["missing"] === true,
  },
]

function PageTables({ page }: { page: InspectedPage }) {
  const tables = useMemo(() => pageTables(page), [page])
  const first = tables[0]
  if (!first) return null
  return (
    <Tabs className="gap-0" defaultValue={first.id}>
      <TabsList className="w-full justify-start border-b" variant="line">
        {tables.map((table) => (
          <TabsTrigger className="flex-none px-2" key={table.id} value={table.id}>
            {table.label}
            <span className="bg-muted text-muted-foreground rounded-full px-1.5 text-xs tabular-nums">
              {table.count.toLocaleString("en-GB")}
            </span>
          </TabsTrigger>
        ))}
      </TabsList>
      {tables.map((table) => (
        <TabsContent className="pt-3" key={table.id} value={table.id}>
          {table.content}
        </TabsContent>
      ))}
    </Tabs>
  )
}

type PageTable = { content: ReactNode; count: number; id: string; label: string }

// Tabs with nothing to show are left out; the checks already say so.
function pageTables(page: InspectedPage): PageTable[] {
  const tables: PageTable[] = []
  if (page.tags) {
    const rows = page.tags.map((tag) => ({
      category: titleCaseToken(tag.category, "Other"),
      found_in: titleCaseToken(tag.foundIn, "Page"),
      id: tag.id,
      vendor: tag.vendor,
    }))
    tables.push({
      content: (
        <DataTable
          columns={TAG_COLUMNS}
          exportFilename="page-tags.csv"
          rowNoun={["Tag", "Tags"]}
          rows={rows}
        />
      ),
      count: rows.length,
      id: "tags",
      label: "Tags",
    })
  }
  if (page.links) {
    const rows = page.links.items.map((link) => ({
      internal: link.internal,
      nofollow: link.nofollow,
      // The text form keeps search and export useful; the cell shows badges.
      scope: `${link.internal ? "Internal" : "External"}${link.nofollow ? ", Nofollow" : ""}`,
      text: link.text,
      url: link.url,
    }))
    tables.push({
      content: (
        <DataTable
          columns={LINK_COLUMNS}
          exportFilename="page-links.csv"
          pageSize={10}
          renderCell={(column, row) =>
            column.key === "scope" ? (
              <span className="flex gap-1">
                <Badge variant={row["internal"] === true ? "secondary" : "outline"}>
                  {row["internal"] === true ? "Internal" : "External"}
                </Badge>
                {row["nofollow"] === true ? <Badge variant="warning">Nofollow</Badge> : null}
              </span>
            ) : null
          }
          rowNoun={["Link", "Links"]}
          rows={rows}
          searchable
          tabs={LINK_TABS}
        />
      ),
      count: page.links.total,
      id: "links",
      label: "Links",
    })
  }
  if (page.images) {
    const rows = page.images.items.map((image) => ({
      alt: image.alt === null ? "Missing" : image.alt || "Decorative",
      described: Boolean(image.alt),
      missing: image.alt === null,
      src: image.src,
    }))
    tables.push({
      content: (
        <DataTable
          columns={IMAGE_COLUMNS}
          exportFilename="page-images.csv"
          pageSize={10}
          renderCell={(column, row) =>
            column.key === "alt" && row["described"] !== true ? (
              <Badge variant={row["missing"] === true ? "warning" : "secondary"}>
                {String(row["alt"])}
              </Badge>
            ) : null
          }
          rowNoun={["Image", "Images"]}
          rows={rows}
          tabs={IMAGE_TABS}
        />
      ),
      count: page.images.total,
      id: "images",
      label: "Images",
    })
  }
  if (page.headings) {
    tables.push({
      content: <HeadingOutline items={page.headings.items} />,
      count: page.headings.items.length,
      id: "headings",
      label: "Headings",
    })
  }
  if (page.structuredData) {
    tables.push({
      content: <StructuredDataBlocks blocks={page.structuredData} />,
      count: page.structuredData.length,
      id: "structured-data",
      label: "Structured Data",
    })
  }
  return tables.filter((table) => table.count > 0)
}

// Indented by level, so skipped levels and stray H1s stand out.
function HeadingOutline({ items }: { items: { level: number; text: string | null }[] }) {
  return (
    <ol
      aria-label="Headings"
      className="max-h-96 overflow-y-auto overscroll-contain rounded-md border py-1.5 text-sm"
    >
      {items.map((heading, index) => (
        <li
          className="flex min-w-0 items-baseline gap-2 px-3 py-1"
          key={`${String(index)}-${heading.text ?? ""}`}
          style={{ paddingLeft: `${String(0.75 + (heading.level - 1) * 1.25)}rem` }}
        >
          <span
            className={cn(
              "w-6 shrink-0 font-mono text-xs",
              heading.level === 1 ? "text-foreground font-semibold" : "text-muted-foreground"
            )}
          >
            H{heading.level}
          </span>
          <span className={cn("min-w-0 wrap-break-word", heading.level === 1 && "font-medium")}>
            {heading.text ?? <span className="text-muted-foreground">Empty Heading</span>}
          </span>
        </li>
      ))}
    </ol>
  )
}

// Each JSON-LD block opens to its formatted source, shown as text and never run.
function StructuredDataBlocks({ blocks }: { blocks: StructuredDataBlock[] }) {
  return (
    <div className="grid gap-2">
      {blocks.map((block, index) => (
        <details className="group rounded-md border" key={`${String(index)}-${block.types.join()}`}>
          <summary className="hover:bg-muted/40 flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-sm">
            <ChevronRightIcon className="text-muted-foreground size-4 shrink-0 transition-transform group-open:rotate-90" />
            <span className="flex min-w-0 flex-1 flex-wrap gap-1">
              {block.types.length > 0 ? (
                block.types.map((type) => (
                  <Badge key={type} variant="secondary">
                    {type}
                  </Badge>
                ))
              ) : (
                <span className="text-muted-foreground">No Type</span>
              )}
            </span>
            {block.valid ? null : <Badge variant="warning">Doesn't Parse</Badge>}
          </summary>
          <pre className="bg-muted/40 max-h-80 overflow-auto border-t px-3 py-2.5 font-mono text-xs wrap-break-word whitespace-pre-wrap">
            {formattedJson(block)}
          </pre>
        </details>
      ))}
    </div>
  )
}

function formattedJson(block: StructuredDataBlock): string {
  const cut = block.truncated ? "\n…" : ""
  if (!block.valid || block.truncated) return block.content + cut
  try {
    return JSON.stringify(JSON.parse(block.content), null, 2)
  } catch {
    return block.content
  }
}

const SITEMAP_COLUMNS: DataColumn[] = [
  { key: "loc", kind: "link", label: "URL", width: "auto" },
  { key: "lastmod", kind: "text", label: "Last Modified", width: 220 },
]

function SitemapEntries({ sitemap }: { sitemap: InspectedSitemap }) {
  const rows = useMemo(
    () => sitemap.entries.map((entry) => ({ lastmod: entry.lastmod, loc: entry.loc })),
    [sitemap.entries]
  )
  const noun = sitemap.index ? (["Sitemap", "Sitemaps"] as const) : (["Page", "Pages"] as const)
  return (
    <DataTable
      columns={SITEMAP_COLUMNS}
      exportFilename="sitemap.csv"
      pageSize={10}
      rowNoun={noun}
      rows={rows}
      searchable
    />
  )
}

const ROBOTS_COLUMNS: DataColumn[] = [
  { key: "user_agents", kind: "text", label: "Crawlers", width: 200 },
  { key: "rule", kind: "text", label: "Rule", width: 110 },
  { key: "path", kind: "text", label: "Path", width: "auto" },
  { key: "crawl_delay", kind: "number", label: "Crawl Delay", unit: "seconds" },
]

const ROBOTS_TABS: DataTableTab[] = [
  { id: "all", label: "All", match: () => true },
  {
    hideWhenEmpty: true,
    id: "disallow",
    label: "Disallow",
    match: (row) => row["rule"] === "Disallow",
  },
  { hideWhenEmpty: true, id: "allow", label: "Allow", match: (row) => row["rule"] === "Allow" },
]

function RobotsRules({ robots }: { robots: InspectedRobots }) {
  const rows = useMemo(
    () =>
      robots.groups.flatMap((group) => {
        const shared = { crawl_delay: group.crawlDelay, user_agents: group.userAgents.join(", ") }
        return [
          ...group.disallow.map((path) => ({
            ...shared,
            path: path || "Nothing",
            rule: "Disallow",
          })),
          ...group.allow.map((path) => ({ ...shared, path, rule: "Allow" })),
        ]
      }),
    [robots.groups]
  )
  return (
    <>
      <DataTable
        columns={ROBOTS_COLUMNS}
        exportFilename="robots-rules.csv"
        pageSize={10}
        rowNoun={["Rule", "Rules"]}
        rows={rows}
        tabs={ROBOTS_TABS}
      />
      {robots.sitemaps.length > 0 ? (
        <ul aria-label="Sitemaps" className="text-muted-foreground grid gap-0.5 text-xs">
          {robots.sitemaps.map((sitemap) => (
            <li className="break-all" key={sitemap}>
              Sitemap: {sitemap}
            </li>
          ))}
        </ul>
      ) : null}
    </>
  )
}
