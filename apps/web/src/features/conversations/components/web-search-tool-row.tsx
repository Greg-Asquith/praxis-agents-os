// apps/web/src/features/conversations/components/web-search-tool-row.tsx
import { GlobeIcon } from "lucide-react"

import { FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { ToolResultCard } from "@/components/tool-ui/result-card"
import { SourceListRow } from "@/components/tool-ui/source"
import { Badge } from "@/components/ui/badge"
import type { ToolActivity } from "@/features/conversations/message-parts"
import {
  webSearchQuery,
  webSearchResult,
} from "@/features/conversations/components/web-search-result"
import { pluralize } from "@/lib/format"

export function WebSearchToolRow({ activity }: { activity: ToolActivity }) {
  if (activity.status === "running") {
    const query = webSearchQuery(activity.args)
    return query ? (
      <FanOutSkeleton
        heading={<WebSearchHeading />}
        label={`Searching ${query}…`}
        summary={`Search: ${query}`}
      />
    ) : null
  }

  if (activity.status !== "completed") {
    return null
  }
  const result = webSearchResult(activity.result)
  if (!result) {
    return null
  }

  const resultCount = result.sources.length
  const resultSummary = `${String(resultCount)} ${pluralize(resultCount, "Result")}`
  const details = [
    { label: "Search", value: result.query },
    { label: "Results", value: resultSummary },
    { label: "Provider", value: result.provider },
    { label: "Model", value: result.model },
  ]
  return (
    <ToolResultCard
      ariaLabel={`Web search results for ${result.query}`}
      details={details}
      heading={<WebSearchHeading />}
      trailing={<Badge variant="success">Done</Badge>}
    >
      {resultCount > 0 ? (
        <div
          aria-label="Web sources"
          className="grid max-h-[min(32rem,60vh)] min-w-0 gap-2 overflow-y-auto overscroll-contain"
          role="list"
        >
          {result.sources.map((source) => (
            <div className="min-w-0" key={source.url} role="listitem">
              <SourceListRow {...source} />
            </div>
          ))}
        </div>
      ) : (
        <p className="text-muted-foreground px-4 py-6 text-center text-sm">
          No sources were returned.
        </p>
      )}
    </ToolResultCard>
  )
}

function WebSearchHeading() {
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <GlobeIcon className="text-muted-foreground size-4 shrink-0" />
      <span>Web Search</span>
    </span>
  )
}
