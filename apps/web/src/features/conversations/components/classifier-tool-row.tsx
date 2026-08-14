// apps/web/src/features/conversations/components/classifier-tool-row.tsx

import { SparklesIcon } from "lucide-react"

import { FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { ToolResultCard } from "@/components/tool-ui/result-card"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { DataTable, type DataColumn } from "@/components/ui/data-table"
import { ActivityStatusBadge } from "@/features/conversations/components/tool-activity-status"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  classifierArgs,
  classifierResult,
} from "@/features/conversations/native-tools/classifier-tool"
import { pluralize } from "@/lib/format"

const CLASSIFIER_COLUMNS: DataColumn[] = [
  { align: "right", key: "index", kind: "number", label: "#" },
  { key: "value", kind: "text", label: "Classified value" },
  { key: "label", kind: "text", label: "Assigned label" },
]

export function ClassifierToolRow({
  activity,
  defaultOpen = false,
}: {
  activity: ToolActivity
  defaultOpen?: boolean
}) {
  if (activity.status === "running") {
    const args = classifierArgs(activity.args)
    const count = args?.items.length ?? 0
    return (
      <FanOutSkeleton
        heading={<ClassifierHeading />}
        label={count > 0 ? `Classifying ${String(count)} items…` : "Classifying items…"}
        {...(args ? { summary: labelSummary(args.labels) } : {})}
      />
    )
  }

  if (
    activity.status === "failed" ||
    activity.status === "denied" ||
    activity.status === "unknown"
  ) {
    return <ClassifierFailureRow activity={activity} />
  }
  if (activity.status !== "completed") {
    return null
  }

  const result = classifierResult(activity.args, activity.result)
  if (result === null) {
    return null
  }
  const args = classifierArgs(activity.args)
  const count = result.rows.length
  return (
    <ToolResultCard
      ariaLabel={`${String(count)} classified ${pluralize(count, "item")}`}
      defaultOpen={defaultOpen}
      details={[
        { label: "Items", value: String(count) },
        { label: "Labels", value: String(result.labels.length) },
        { label: "Provider", summary: false, value: result.modelProvider },
        { label: "Model", summary: false, value: result.model },
        ...(args?.instructions
          ? [{ label: "Instructions", summary: false, value: args.instructions }]
          : []),
      ]}
      heading={<ClassifierHeading />}
      trailing={<Badge variant="success">{String(count)} Classified</Badge>}
    >
      <DataTable
        columns={CLASSIFIER_COLUMNS}
        exportFilename="classifications.csv"
        header={<LabelDistribution labels={result.labels} rows={result.rows} />}
        pageSize={25}
        rows={result.rows.map((row) => ({ ...row, index: row.index + 1 }))}
      />
    </ToolResultCard>
  )
}

function ClassifierFailureRow({ activity }: { activity: ToolActivity }) {
  const message =
    typeof activity.result === "string" && activity.result.trim()
      ? activity.result
      : activity.status === "denied"
        ? "This classification was declined. No items were sent to the helper model."
        : "The classification did not finish. No labels were confirmed."
  return (
    <ToolResultCard
      ariaLabel="Classification failed"
      defaultOpen
      details={[]}
      heading={<ClassifierHeading />}
      trailing={<ActivityStatusBadge status={activity.status} />}
    >
      <Alert variant="destructive">
        <AlertTitle>
          {activity.status === "denied" ? "Classification declined" : "Classification failed"}
        </AlertTitle>
        <AlertDescription>{message}</AlertDescription>
      </Alert>
    </ToolResultCard>
  )
}

function LabelDistribution({ labels, rows }: { labels: string[]; rows: { label: string }[] }) {
  const counts = new Map(labels.map((label) => [label, 0]))
  for (const row of rows) {
    counts.set(row.label, (counts.get(row.label) ?? 0) + 1)
  }
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-1.5" aria-label="Label distribution">
      {labels.map((label) => (
        <Badge key={label} variant="secondary">
          {label} · {String(counts.get(label) ?? 0)}
        </Badge>
      ))}
    </div>
  )
}

function ClassifierHeading() {
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <SparklesIcon className="text-muted-foreground size-4 shrink-0" />
      <span>Classify</span>
    </span>
  )
}

function labelSummary(labels: string[]): string {
  return `${String(labels.length)} ${pluralize(labels.length, "label")}: ${labels.join(", ")}`
}
