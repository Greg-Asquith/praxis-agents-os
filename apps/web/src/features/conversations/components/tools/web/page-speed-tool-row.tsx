// apps/web/src/features/conversations/components/tools/web/page-speed-tool-row.tsx

import { useQuery } from "@tanstack/react-query"
import { ChevronRightIcon, ExternalLinkIcon, GaugeIcon, TriangleAlertIcon } from "lucide-react"
import { useMemo, type ReactNode } from "react"

import { FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { parseResultPreview } from "@/components/tool-ui/result-preview"
import { ResultPreviewNotice } from "@/components/tool-ui/result-preview-notice"
import { ToolResultCard } from "@/components/tool-ui/result-card"
import { RetainedResult } from "@/components/tool-ui/retained-result"
import { ToolHeading } from "@/components/tool-ui/tool-heading"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { DataTable, type DataColumn } from "@/components/ui/data-table"
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { pageSpeedReportQueryOptions } from "@/features/conversations/api/get-page-speed-report"
import {
  type FailedAudit,
  type PageSpeedReport,
  pageSpeedReport,
} from "@/features/conversations/components/tools/web/page-speed-report"
import {
  CATEGORY_LABELS,
  METRICS,
  OUTCOMES,
  PAGE_SPEED_TABS,
  type FieldData,
  type FieldMetric,
  type LabMetrics,
  type MetricKey,
  type PageOutcome,
  type PageSpeedCategory,
  type PageSpeedResult,
  type PageSpeedRow,
  type Rating,
  type Strategy,
  formatMetric,
  metricRating,
  originOf,
  pageSpeedArgsCount,
  pageSpeedResult,
  scoreRating,
} from "@/features/conversations/components/tools/web/page-speed-result"
import { webErrorText } from "@/features/conversations/components/tools/web/web-error-text"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { formatBytes, formatDateTime, pluralize, titleCaseToken } from "@/lib/format"
import { cn } from "@/lib/utils"

const HEADING = <ToolHeading icon={GaugeIcon}>Measure Page Speed</ToolHeading>

// Timings start hidden; the Columns menu and each page's detail show them.
const COLUMNS: DataColumn[] = [
  { key: "url", kind: "text", label: "Page", width: "auto" },
  { key: "score", kind: "number", label: "Score", width: 150 },
  { key: "cwv", kind: "text", label: "Core Web Vitals", width: 150 },
  { key: "issue", kind: "text", label: "Biggest Issue", width: 220 },
  { key: "lcp", kind: "number", label: "LCP", hidden: true },
  { key: "inp", kind: "number", label: "INP", hidden: true },
  { key: "cls", kind: "number", label: "CLS", hidden: true },
]

const METRIC_ROWS: MetricKey[] = [
  "lcp_ms",
  "inp_ms",
  "cls",
  "fcp_ms",
  "ttfb_ms",
  "tbt_ms",
  "speed_index_ms",
]

const RATING_TEXT: Record<Rating, string> = {
  good: "text-success",
  needs_improvement: "text-warning-text dark:text-warning",
  poor: "text-destructive",
}

export function PageSpeedToolRow({
  activity,
  defaultOpen = false,
}: {
  activity: ToolActivity
  defaultOpen?: boolean
}) {
  if (activity.status === "running") {
    const count = pageSpeedArgsCount(activity.args)
    return count ? (
      <FanOutSkeleton
        running
        heading={HEADING}
        label={`Testing ${String(count)} ${pluralize(count, "page")}…`}
      />
    ) : null
  }
  if (activity.status !== "completed") return null
  const envelope = parseResultPreview(activity.result)
  const data = envelope?.data ?? activity.result
  if (pageSpeedResult(data) === null) return null
  const render = (visible: unknown, _incomplete: boolean, control?: ReactNode) => (
    <PageSpeedCard
      data={visible}
      defaultOpen={defaultOpen}
      notice={
        envelope ? (
          <>
            {control}
            <ResultPreviewNotice data={visible} preview={envelope} />
          </>
        ) : null
      }
    />
  )
  return envelope ? (
    <RetainedResult
      key={envelope.fileId}
      preview={envelope}
      validate={(value) => pageSpeedResult(value) !== null}
    >
      {render}
    </RetainedResult>
  ) : (
    render(data, false)
  )
}

function PageSpeedCard({
  data,
  defaultOpen,
  notice,
}: {
  data: unknown
  defaultOpen: boolean
  notice: ReactNode
}) {
  // One parse per result keeps each row's page, and any open popover, the same between renders.
  const result = useMemo(() => pageSpeedResult(data), [data])
  if (result === null) return null
  const counts = outcomeCounts(result.rows)
  const details = [
    { label: "Pages", value: result.rows.length.toLocaleString("en-GB") },
    { label: "Device", value: result.strategy === "mobile" ? "Mobile" : "Desktop" },
    { label: "Tested", value: formatDateTime(result.testedAt) },
  ]
  if (counts.not_tested > 0) {
    details.push({ label: "Not Tested", value: counts.not_tested.toLocaleString("en-GB") })
  }
  const median = result.rows.length > 1 ? medianScore(result) : null
  if (median) {
    details.push({
      label: `Median ${CATEGORY_LABELS[median.category]}`,
      value: `${String(median.score)}, ${OUTCOMES[scoreRating(median.score)].label}`,
    })
  }
  const [single] = result.rows
  return (
    <ToolResultCard
      ariaLabel={`Measured page speed for ${String(result.rows.length)} ${pluralize(result.rows.length, "page")}`}
      defaultOpen={defaultOpen}
      details={details}
      heading={HEADING}
      trailing={<SummaryBadge counts={counts} />}
    >
      <div className="grid min-w-0 gap-4">
        {notice}
        {result.rows.length === 1 && single && single.outcome !== "not_tested" ? (
          <PageDetail result={result} row={single} />
        ) : (
          <PageTable result={result} />
        )}
      </div>
    </ToolResultCard>
  )
}

function PageTable({ result }: { result: PageSpeedResult }) {
  const byUrl = useMemo(
    () => new Map(result.rows.map((row) => [row.requestedUrl, row])),
    [result.rows]
  )
  const rows = useMemo(
    () =>
      [...result.rows]
        .sort((left, right) => sortScore(left) - sortScore(right))
        .map((row) => {
          const issue = row.topIssues[0]
          return {
            cls: row.lab?.cls ?? null,
            cwv: row.field?.coreWebVitals ?? null,
            inp: row.field?.metrics.inp_ms?.p75 ?? null,
            issue: row.errorClass
              ? (webErrorText(row.errorClass) ?? "Not Tested")
              : issue
                ? titleCaseToken(issue.audit, "")
                : null,
            lcp: row.lab?.lcp_ms ?? null,
            outcome: row.outcome,
            score: row.lead?.score ?? null,
            url: row.requestedUrl,
          }
        }),
    [result.rows]
  )
  return (
    <DataTable
      columns={COLUMNS}
      exportFilename="page-speed.csv"
      pageSize={10}
      renderCell={(column, row) => {
        const page = byUrl.get(String(row["url"]))
        return page ? <PageCell column={column} page={page} result={result} /> : null
      }}
      rowDetails={false}
      rowNoun={["page", "pages"]}
      rows={rows}
      searchable
      tabs={PAGE_SPEED_TABS}
    />
  )
}

function PageCell({
  column,
  page,
  result,
}: {
  column: DataColumn
  page: PageSpeedRow
  result: PageSpeedResult
}) {
  if (column.key === "url") {
    return (
      <Popover>
        <PopoverTrigger
          render={
            <Button
              aria-label={`Show the page speed detail for ${page.requestedUrl}`}
              className="h-auto min-h-7 max-w-full min-w-0 justify-start gap-1 px-1.5 py-1 text-left font-normal"
              size="sm"
              type="button"
              variant="ghost"
            />
          }
        >
          <span className="min-w-0 truncate">{page.requestedUrl}</span>
          <ChevronRightIcon className="text-muted-foreground shrink-0" />
        </PopoverTrigger>
        <PopoverContent
          align="start"
          className="max-h-[min(36rem,80vh)] w-[min(38rem,calc(100vw-2rem))] gap-3 overflow-y-auto"
        >
          <PopoverHeader>
            <PopoverTitle className="wrap-anywhere">{page.requestedUrl}</PopoverTitle>
            {page.finalUrl ? (
              <PopoverDescription className="wrap-anywhere">
                Redirected to {page.finalUrl}
              </PopoverDescription>
            ) : null}
          </PopoverHeader>
          {page.outcome === "not_tested" ? (
            <p className="text-muted-foreground text-xs">
              {webErrorText(page.errorClass) ?? "This page wasn't tested."}
            </p>
          ) : (
            <PageDetail result={result} row={page} />
          )}
        </PopoverContent>
      </Popover>
    )
  }
  if (column.key === "score") return <ScoreText page={page} />
  if (column.key === "cwv")
    return page.outcome === "not_tested" ? null : <VitalsBadge field={page.field} />
  if (column.key === "lcp" && page.lab?.lcp_ms !== undefined) {
    return (
      <MetricValue
        metric="lcp_ms"
        rating={metricRating("lcp_ms", page.lab.lcp_ms, result.strategy)}
        value={page.lab.lcp_ms}
      />
    )
  }
  if (column.key === "cls" && page.lab?.cls !== undefined) {
    return (
      <MetricValue
        metric="cls"
        rating={metricRating("cls", page.lab.cls, result.strategy)}
        value={page.lab.cls}
      />
    )
  }
  if (column.key === "inp" && page.field?.metrics.inp_ms) {
    const { p75, rating } = page.field.metrics.inp_ms
    return <MetricValue metric="inp_ms" rating={rating} value={p75} />
  }
  return null
}

function PageDetail({ result, row }: { result: PageSpeedResult; row: PageSpeedRow }) {
  const origin = originOf(row.requestedUrl)
  const site = origin ? (result.origins.get(origin) ?? null) : null
  const categories = result.categories.filter((category) => row.scores[category] != null)
  return (
    <div className="grid min-w-0 gap-3">
      {categories.length ? (
        <ul aria-label="Scores" className="flex min-w-0 flex-wrap gap-x-5 gap-y-2 text-sm">
          {categories.map((category) => (
            <li className="flex items-center gap-2" key={category}>
              {CATEGORY_LABELS[category]}
              <ScoreBadge score={row.scores[category] ?? 0} />
            </li>
          ))}
        </ul>
      ) : null}
      <Tabs className="gap-0" defaultValue="metrics">
        <TabsList className="w-full justify-start border-b" variant="line">
          <TabsTrigger className="flex-none px-2" value="metrics">
            All Metrics
          </TabsTrigger>
          <TabsTrigger className="flex-none px-2" value="issues">
            Issues
          </TabsTrigger>
        </TabsList>
        <TabsContent className="pt-3" value="metrics">
          <MetricsTable lab={row.lab} page={row.field} site={site} strategy={result.strategy} />
        </TabsContent>
        <TabsContent className="pt-3" value="issues">
          {row.report && result.reportFileId ? (
            <ReportDetail
              fileId={result.reportFileId}
              range={row.report}
              requestedUrl={row.requestedUrl}
            />
          ) : (
            <p className="text-muted-foreground text-xs">
              The detailed report for this page wasn't saved.
            </p>
          )}
        </TabsContent>
      </Tabs>
      <a
        className="text-link inline-flex w-fit items-center gap-1 text-xs hover:underline"
        // The agent's own URL; Google's page runs the test again in the person's browser.
        href={`https://pagespeed.web.dev/analysis?url=${encodeURIComponent(row.requestedUrl)}&form_factor=${result.strategy}`}
        rel="noreferrer"
        target="_blank"
      >
        Open in PageSpeed Insights
        <ExternalLinkIcon aria-hidden="true" className="size-3" />
      </a>
    </div>
  )
}

function MetricsTable({
  lab,
  page,
  site,
  strategy,
}: {
  lab: LabMetrics | null
  page: FieldData | null
  site: FieldData | null
  strategy: Strategy
}) {
  return (
    <div className="grid min-w-0 gap-2">
      <Table className="text-xs">
        <TableHeader>
          <TableRow>
            <TableHead>Metric</TableHead>
            <TableHead className="text-right">Google's Test</TableHead>
            <TableHead className="text-right">Visitors, This Page</TableHead>
            <TableHead className="text-right">Visitors, Whole Site</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {METRIC_ROWS.map((key) => {
            const labValue = lab?.[key]
            const pageMetric = page?.metrics[key]
            const siteMetric = site?.metrics[key]
            if (labValue === undefined && !pageMetric && !siteMetric) return null
            return (
              <TableRow key={key}>
                <TableCell>{METRICS[key].name}</TableCell>
                <TableCell className="text-right">
                  {labValue === undefined ? (
                    "—"
                  ) : (
                    <MetricValue
                      metric={key}
                      rating={metricRating(key, labValue, strategy)}
                      value={labValue}
                    />
                  )}
                </TableCell>
                <TableCell className="text-right">
                  <FieldValue metric={key} value={pageMetric} />
                </TableCell>
                <TableCell className="text-right">
                  <FieldValue metric={key} value={siteMetric} />
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
      <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-xs">
        <span>Core Web Vitals for visitors:</span>
        <VitalsBadge field={page} />
      </div>
      <p className="text-muted-foreground text-xs">
        Visitor figures are the 75th percentile of real Chrome visits over the last 28 days.
      </p>
    </div>
  )
}

function ReportDetail({
  fileId,
  range,
  requestedUrl,
}: {
  fileId: string
  range: { length: number; offset: number }
  requestedUrl: string
}) {
  const report = useQuery({
    ...pageSpeedReportQueryOptions(fileId),
    select: (content) => pageSpeedReport(content, range, requestedUrl),
  })
  if (report.isPending) {
    return (
      <p className="text-muted-foreground text-xs" role="status">
        Loading the issues…
      </p>
    )
  }
  if (report.isError || !report.data) {
    return (
      <p className="text-destructive text-xs" role="alert">
        The issues couldn't be loaded.
      </p>
    )
  }
  return <IssueList report={report.data} />
}

function IssueList({ report }: { report: PageSpeedReport }) {
  // Biggest saving first, then the remaining issues in Lighthouse's order.
  const audits = [...report.failedAudits].sort(
    (left, right) => right.savingMs - left.savingMs || right.savingBytes - left.savingBytes
  )
  const footnote = [
    `${report.passedAudits.toLocaleString("en-GB")} ${pluralize(report.passedAudits, "check")} passed.`,
    report.lcpElement?.selector ? `Largest element on screen: ${report.lcpElement.selector}.` : "",
    report.truncated ? "Some issues were left out to keep the report small." : "",
  ]
  return (
    <div className="grid min-w-0 gap-2">
      {report.runWarnings.length ? (
        <ul aria-label="Test Warnings" className="grid min-w-0 gap-1 text-xs">
          {report.runWarnings.map((warning, index) => (
            <li className="flex min-w-0 items-start gap-1.5" key={`${String(index)}-${warning}`}>
              <TriangleAlertIcon
                aria-hidden="true"
                className="text-warning mt-0.5 size-3.5 shrink-0"
              />
              <span className="wrap-anywhere">{warning}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {audits.length ? (
        <ul className="divide-border grid min-w-0 divide-y rounded-md border">
          {audits.map((audit) => (
            <li className="min-w-0" key={audit.id}>
              <IssueRow audit={audit} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs">No issues found.</p>
      )}
      <p className="text-muted-foreground text-xs wrap-anywhere">
        {footnote.filter(Boolean).join(" ")}
      </p>
    </div>
  )
}

function IssueRow({ audit }: { audit: FailedAudit }) {
  const saving = savingText(audit)
  return (
    <Popover>
      <PopoverTrigger
        render={
          <Button
            className="h-auto w-full min-w-0 justify-between gap-3 rounded-none px-2 py-1.5 text-left font-normal"
            size="sm"
            type="button"
            variant="ghost"
          />
        }
      >
        <span className="min-w-0 truncate">{audit.title}</span>
        <span className="text-muted-foreground shrink-0 text-xs">
          {saving ? `Could save ${saving}` : CATEGORY_LABELS[audit.category]}
        </span>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="max-h-[min(30rem,75vh)] w-[min(34rem,calc(100vw-2rem))] gap-3 overflow-y-auto"
      >
        <PopoverHeader>
          <PopoverTitle className="wrap-anywhere">{audit.title}</PopoverTitle>
          {audit.description ? (
            <PopoverDescription className="wrap-anywhere">{audit.description}</PopoverDescription>
          ) : null}
        </PopoverHeader>
        {audit.displayValue ? <p className="text-xs">{audit.displayValue}</p> : null}
        {audit.items.length ? <IssueItems audit={audit} /> : null}
      </PopoverContent>
    </Popover>
  )
}

function IssueItems({ audit }: { audit: FailedAudit }) {
  const showWasted = audit.items.some((item) => item.wastedBytes !== null || item.wastedMs !== null)
  return (
    <div className="grid min-w-0 gap-1">
      <Table className="text-xs">
        <TableHeader>
          <TableRow>
            <TableHead>Resource or Element</TableHead>
            <TableHead className="text-right">Size</TableHead>
            {showWasted ? <TableHead className="text-right">Could Save</TableHead> : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {audit.items.map((item, index) => (
            // eslint-disable-next-line react-x/no-array-index-key -- Items have no ID, and the list never reorders.
            <TableRow key={index}>
              <TableCell className="max-w-0 min-w-0">
                <span className="block truncate" title={item.url ?? item.selector ?? undefined}>
                  {item.url ?? item.selector ?? item.label ?? item.entity ?? "—"}
                </span>
                {item.snippet ? (
                  <code className="text-muted-foreground block truncate">{item.snippet}</code>
                ) : null}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {item.totalBytes === null ? "—" : formatBytes(item.totalBytes)}
              </TableCell>
              {showWasted ? (
                <TableCell className="text-right tabular-nums">
                  {item.wastedMs
                    ? formatMetric("lcp_ms", item.wastedMs)
                    : item.wastedBytes !== null
                      ? formatBytes(item.wastedBytes)
                      : "—"}
                </TableCell>
              ) : null}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {audit.itemCount > audit.items.length ? (
        <p className="text-muted-foreground text-xs">
          Showing {audit.items.length} of {audit.itemCount}.
        </p>
      ) : null}
    </div>
  )
}

function ScoreText({ page }: { page: PageSpeedRow }) {
  if (page.outcome === "not_tested" || page.lead === null) {
    return <span className="text-muted-foreground">Not Tested</span>
  }
  const { score } = page.lead
  return (
    <span className="flex items-center gap-2">
      <ScoreBadge score={score} />
      <span aria-hidden="true" className="text-muted-foreground">
        {OUTCOMES[scoreRating(score)].label}
      </span>
    </span>
  )
}

function ScoreBadge({ score }: { score: number }) {
  const { badge, label } = OUTCOMES[scoreRating(score)]
  return (
    <Badge className="tabular-nums" variant={badge}>
      {score}
      <span className="sr-only"> out of 100, {label}</span>
    </Badge>
  )
}

// The median of the lead scores, over pages tested for the call's lead category.
function medianScore(
  result: PageSpeedResult
): { category: PageSpeedCategory; score: number } | null {
  const category = result.categories.includes("performance") ? "performance" : result.categories[0]
  if (category === undefined) return null
  const scores = result.rows
    .flatMap((row) =>
      row.outcome !== "not_tested" && row.lead?.category === category ? row.lead.score : []
    )
    .sort((left, right) => left - right)
  if (!scores.length) return null
  const middle = Math.floor(scores.length / 2)
  const score =
    scores.length % 2
      ? (scores[middle] ?? 0)
      : Math.round(((scores[middle - 1] ?? 0) + (scores[middle] ?? 0)) / 2)
  return { category, score }
}

function MetricValue({
  metric,
  rating,
  value,
}: {
  metric: MetricKey
  rating: Rating | null
  value: number
}) {
  return (
    <span className={cn("tabular-nums", rating && RATING_TEXT[rating])}>
      {formatMetric(metric, value)}
      {rating ? <span className="sr-only">, {OUTCOMES[rating].label}</span> : null}
    </span>
  )
}

function FieldValue({ metric, value }: { metric: MetricKey; value: FieldMetric | undefined }) {
  return value ? <MetricValue metric={metric} rating={value.rating} value={value.p75} /> : "—"
}

function VitalsBadge({ field }: { field: FieldData | null }) {
  if (!field?.coreWebVitals) return <Badge variant="secondary">No Visitor Data</Badge>
  return field.coreWebVitals === "passed" ? (
    <Badge variant="success">Passed</Badge>
  ) : (
    <Badge variant="destructive">Failed</Badge>
  )
}

function SummaryBadge({ counts }: { counts: Record<PageOutcome, number> }) {
  if (counts.poor > 0) return <Badge variant="destructive">{counts.poor} Poor</Badge>
  if (counts.not_tested > 0) return <Badge variant="warning">{counts.not_tested} Not Tested</Badge>
  return <Badge variant="success">Done</Badge>
}

function savingText(audit: FailedAudit): string | null {
  if (audit.savingMs > 0) return formatMetric("lcp_ms", audit.savingMs)
  return audit.savingBytes > 0 ? formatBytes(audit.savingBytes) : null
}

function sortScore(row: PageSpeedRow): number {
  // Lowest score first; pages that weren't tested go last.
  return row.outcome === "not_tested" ? 101 : (row.lead?.score ?? 100)
}

function outcomeCounts(rows: PageSpeedRow[]): Record<PageOutcome, number> {
  const counts = { good: 0, needs_improvement: 0, poor: 0, not_tested: 0 }
  for (const row of rows) counts[row.outcome] += 1
  return counts
}
