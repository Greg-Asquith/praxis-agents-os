// apps/web/src/features/conversations/components/completion-report-row.tsx

import { ClipboardCheckIcon } from "lucide-react"

import { FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { ToolResultCard } from "@/components/tool-ui/result-card"
import { Badge } from "@/components/ui/badge"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { completionReport } from "@/features/conversations/native-tools/completion-tool"
import { pluralize } from "@/lib/format"

type CompletionReportRowProps = {
  activity: ToolActivity
  defaultOpen?: boolean
}

export function CompletionReportRow({ activity, defaultOpen = false }: CompletionReportRowProps) {
  if (activity.status === "running") {
    return (
      <FanOutSkeleton
        heading={<CompletionReportHeading />}
        label="Checking completion…"
        summary="Preparing the completion verdict"
      />
    )
  }
  if (activity.status !== "completed") {
    return null
  }

  const report = completionReport(activity.result)
  if (!report) {
    return null
  }

  const passed = report.status === "pass"
  const evidenceCount = report.evidence.length
  return (
    <ToolResultCard
      ariaLabel={`Completion check ${passed ? "passed" : "failed"}`}
      defaultOpen={defaultOpen}
      details={[
        { label: "Summary", value: report.summary },
        {
          label: "Evidence",
          value: `${String(evidenceCount)} ${pluralize(evidenceCount, "Item")}`,
        },
      ]}
      heading={<CompletionReportHeading />}
      trailing={
        <Badge variant={passed ? "success" : "destructive"}>{passed ? "Passed" : "Failed"}</Badge>
      }
    >
      {evidenceCount > 0 ? (
        <ol aria-label="Completion evidence" className="divide-border divide-y">
          {report.evidence.map((item, index) => (
            <li
              className="flex min-w-0 items-start gap-2 py-2 text-sm"
              key={`${String(index)}:${item}`}
            >
              <span className="text-muted-foreground w-4 shrink-0 text-right tabular-nums">
                {String(index + 1)}.
              </span>
              <span className="min-w-0 wrap-break-word">{item}</span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="text-muted-foreground text-sm">No supporting evidence was provided.</p>
      )}
    </ToolResultCard>
  )
}

function CompletionReportHeading() {
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <ClipboardCheckIcon className="text-muted-foreground size-4 shrink-0" />
      <span>Completion Check</span>
    </span>
  )
}
