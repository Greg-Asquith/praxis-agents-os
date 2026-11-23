// apps/web/src/features/conversations/components/check-urls-tool-row.tsx

import { ListChecksIcon } from "lucide-react"
import { useMemo, type ReactNode } from "react"

import { FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { parseResultPreview } from "@/components/tool-ui/result-preview"
import { ResultPreviewNotice } from "@/components/tool-ui/result-preview-notice"
import { ToolResultCard } from "@/components/tool-ui/result-card"
import { RetainedResult } from "@/components/tool-ui/retained-result"
import { ToolHeading } from "@/components/tool-ui/tool-heading"
import { Badge } from "@/components/ui/badge"
import { DataTable, type DataColumn } from "@/components/ui/data-table"
import {
  CHECKED_URL_OUTCOMES,
  CHECKED_URL_TABS,
  type CheckUrlsResult,
  type CheckedUrlOutcome,
  checkUrlsArgsCount,
  checkUrlsResult,
} from "@/features/conversations/components/check-urls-result"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { pluralize, titleCaseToken } from "@/lib/format"

const HEADING = <ToolHeading icon={ListChecksIcon}>Check URLs</ToolHeading>

const COLUMNS: DataColumn[] = [
  { key: "url", kind: "link", label: "URL", width: "auto" },
  { key: "outcome", kind: "text", label: "Result", width: 120 },
  { key: "status", kind: "text", label: "Status", width: 110 },
  { key: "redirects", kind: "text", label: "Redirects", width: 140 },
  { key: "final_url", kind: "link", label: "Final URL", hidden: true },
  { key: "content_type", kind: "text", label: "Content Type", hidden: true },
  { key: "ttfb", kind: "number", label: "First Byte", unit: "milliseconds", isMetric: true },
]

const PAGE_COLUMNS: DataColumn[] = [
  { key: "title", kind: "text", label: "Title", width: 220 },
  { key: "h1_count", kind: "number", label: "H1s", isMetric: true },
]

export function CheckUrlsToolRow({
  activity,
  defaultOpen = false,
}: {
  activity: ToolActivity
  defaultOpen?: boolean
}) {
  if (activity.status === "running") {
    const count = checkUrlsArgsCount(activity.args)
    const label = `Checking ${String(count)} ${pluralize(count ?? 0, "URL")}…`
    return count ? <FanOutSkeleton running heading={HEADING} label={label} /> : null
  }
  if (activity.status !== "completed") return null
  const envelope = parseResultPreview(activity.result)
  const data = envelope?.data ?? activity.result
  if (checkUrlsResult(data) === null) return null
  const render = (visible: unknown, _incomplete: boolean, control?: ReactNode) => {
    const result = checkUrlsResult(visible)
    return result ? (
      <CheckUrlsCard
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
      validate={(value) => checkUrlsResult(value) !== null}
    >
      {render}
    </RetainedResult>
  ) : (
    render(data, false)
  )
}

function CheckUrlsCard({
  defaultOpen,
  notice,
  result,
}: {
  defaultOpen: boolean
  notice: ReactNode
  result: CheckUrlsResult
}) {
  const counts = outcomeCounts(result)
  const rows = useMemo(
    () =>
      result.rows.map((row) => ({
        content_type: row.contentType,
        final_url: row.finalUrl,
        h1_count: row.h1Count,
        outcome: row.outcome,
        redirects: row.redirects.map((hop) => String(hop.status)).join(" → "),
        status: row.status ?? titleCaseToken(row.errorClass ?? "", "Failed"),
        title: row.title,
        ttfb: row.timeToFirstByteMs,
        url: row.requestedUrl,
      })),
    [result.rows]
  )
  const details = [{ label: "URLs", value: result.rows.length.toLocaleString("en-GB") }]
  for (const outcome of ["broken", "blocked", "not_checked"] as const) {
    if (counts[outcome] > 0) {
      const { label } = CHECKED_URL_OUTCOMES[outcome]
      details.push({ label, value: counts[outcome].toLocaleString("en-GB") })
    }
  }
  return (
    <ToolResultCard
      ariaLabel={`Checked ${String(result.rows.length)} ${pluralize(result.rows.length, "URL")}`}
      defaultOpen={defaultOpen}
      details={details}
      heading={HEADING}
      trailing={<SummaryBadge counts={counts} />}
    >
      <div className="grid min-w-0 gap-3">
        {notice}
        <DataTable
          columns={result.pageFacts ? [...COLUMNS, ...PAGE_COLUMNS] : COLUMNS}
          exportFilename="checked-urls.csv"
          pageSize={10}
          renderCell={(column, row) => {
            if (column.key !== "outcome") return null
            const { badge, label } = CHECKED_URL_OUTCOMES[row["outcome"] as CheckedUrlOutcome]
            return <Badge variant={badge}>{label}</Badge>
          }}
          rowNoun={["URL", "URLs"]}
          rows={rows}
          searchable
          tabs={CHECKED_URL_TABS}
        />
      </div>
    </ToolResultCard>
  )
}

function SummaryBadge({ counts }: { counts: Record<CheckedUrlOutcome, number> }) {
  if (counts.broken > 0) return <Badge variant="destructive">{counts.broken} Broken</Badge>
  if (counts.not_checked > 0)
    return <Badge variant="warning">{counts.not_checked} Not Checked</Badge>
  return <Badge variant="success">Done</Badge>
}

function outcomeCounts(result: CheckUrlsResult): Record<CheckedUrlOutcome, number> {
  const counts = { ok: 0, redirected: 0, broken: 0, blocked: 0, not_checked: 0 }
  for (const row of result.rows) counts[row.outcome] += 1
  return counts
}
