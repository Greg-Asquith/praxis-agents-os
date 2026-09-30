// apps/web/src/features/conversations/components/tool-search-row.tsx

import { SearchIcon } from "lucide-react"

import { FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { ToolResultCard } from "@/components/tool-ui/result-card"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { ActivityStatusBadge } from "@/features/conversations/components/tool-activity-status"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  toolSearchQuery,
  toolSearchResult,
} from "@/features/conversations/native-tools/tool-search"
import { useToolLabels } from "@/features/tools/use-tool-labels"
import { pluralize } from "@/lib/format"

type ToolSearchRowProps = {
  activity: ToolActivity
  defaultOpen: boolean
}

export function ToolSearchRow({ activity, defaultOpen }: ToolSearchRowProps) {
  const query = toolSearchQuery(activity.args)
  if (activity.status === "running" || activity.status === "awaiting_approval") {
    return (
      <FanOutSkeleton
        heading={<ToolSearchHeading />}
        label={query ? `Finding tools for ${query}…` : "Finding tools…"}
        {...(query ? { summary: `Search: ${query}` } : {})}
      />
    )
  }
  const result = activity.status === "completed" ? toolSearchResult(activity.result) : null
  if (!result) {
    return <ToolSearchFailureRow activity={activity} query={query} />
  }
  return <FoundToolsCard defaultOpen={defaultOpen} query={query} toolNames={result.toolNames} />
}

function FoundToolsCard({
  defaultOpen,
  query,
  toolNames,
}: {
  defaultOpen: boolean
  query: string | null
  toolNames: string[]
}) {
  const labelFor = useToolLabels()
  const countLabel = `${String(toolNames.length)} ${pluralize(toolNames.length, "Tool")}`
  return (
    <ToolResultCard
      ariaLabel={query ? `Tools found for ${query}` : "Tools found"}
      defaultOpen={defaultOpen}
      details={[
        ...(query ? [{ label: "Search", value: query }] : []),
        { label: "Found", value: countLabel },
      ]}
      heading={<ToolSearchHeading />}
      trailing={<Badge variant={toolNames.length > 0 ? "success" : "outline"}>{countLabel}</Badge>}
    >
      {toolNames.length > 0 ? (
        <ul aria-label="Tools found" className="divide-border divide-y rounded-lg border">
          {toolNames.map((name) => (
            <li className="truncate px-3 py-2 text-sm" key={name}>
              {labelFor(name)}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-muted-foreground px-4 py-6 text-center text-sm">
          No matching tools were found.
        </p>
      )}
    </ToolResultCard>
  )
}

function ToolSearchFailureRow({
  activity,
  query,
}: Pick<ToolSearchRowProps, "activity"> & { query: string | null }) {
  const message =
    typeof activity.result === "string" && activity.result.trim()
      ? activity.result
      : "The tool search did not finish."
  return (
    <ToolResultCard
      ariaLabel="Tool search failed"
      defaultOpen
      details={query ? [{ label: "Search", value: query }] : []}
      heading={<ToolSearchHeading />}
      trailing={<ActivityStatusBadge status={activity.status} />}
    >
      <Alert variant="destructive">
        <AlertTitle>What Went Wrong</AlertTitle>
        <AlertDescription className="whitespace-pre-wrap">{message}</AlertDescription>
      </Alert>
    </ToolResultCard>
  )
}

function ToolSearchHeading() {
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <SearchIcon className="text-muted-foreground size-4 shrink-0" />
      <span className="truncate">Find Tools</span>
    </span>
  )
}
