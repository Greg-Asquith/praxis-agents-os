// apps/web/src/features/conversations/components/tools/web/ask-url-tool-row.tsx

import { LinkIcon } from "lucide-react"

import { MarkdownContent } from "@/components/markdown/markdown-content"
import { ToolHeading } from "@/components/tool-ui/tool-heading"
import { FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { ToolResultCard } from "@/components/tool-ui/result-card"
import { SourceListRow } from "@/components/tool-ui/source"
import { Badge } from "@/components/ui/badge"
import {
  askUrlResult,
  askUrlUrl,
} from "@/features/conversations/components/tools/web/ask-url-result"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { pluralize } from "@/lib/format"

export function AskUrlToolRow({
  activity,
  defaultOpen = false,
}: {
  activity: ToolActivity
  defaultOpen?: boolean
}) {
  if (activity.status === "running") {
    const url = askUrlUrl(activity.args)
    return url ? (
      <FanOutSkeleton
        running
        heading={<ToolHeading icon={LinkIcon}>Ask About a Page</ToolHeading>}
        label={`Reading ${url}…`}
        summary={`URL: ${url}`}
      />
    ) : null
  }

  if (activity.status !== "completed") {
    return null
  }
  const result = askUrlResult(activity.result)
  if (!result) {
    return null
  }

  const sourceCount = result.sources.length
  const details = [
    { label: "Question", value: result.question },
    { label: "URL", value: result.url },
    { label: "Sources", value: `${String(sourceCount)} ${pluralize(sourceCount, "Source")}` },
    { label: "Provider", value: result.provider },
    { label: "Model", value: result.model },
  ]
  return (
    <ToolResultCard
      ariaLabel={`Answer from ${result.url}`}
      defaultOpen={defaultOpen}
      details={details}
      heading={<ToolHeading icon={LinkIcon}>Ask About a Page</ToolHeading>}
      trailing={<Badge variant="success">Done</Badge>}
    >
      <div className="grid min-w-0 gap-4">
        <div className="grid min-w-0 gap-2">
          <p className="text-muted-foreground text-xs font-medium">Answer</p>
          <div
            aria-label="Answer"
            className="border-input bg-muted/40 max-h-[min(32rem,60vh)] min-w-0 overflow-y-auto overscroll-contain rounded-md border px-3 py-2.5"
          >
            <MarkdownContent content={result.answer} />
          </div>
        </div>
        {sourceCount > 0 ? (
          <div className="grid min-w-0 gap-2">
            <p className="text-muted-foreground text-xs font-medium">Sources</p>
            <div aria-label="Page sources" className="grid min-w-0 gap-2" role="list">
              {result.sources.map((source) => (
                <div className="min-w-0" key={source.url} role="listitem">
                  <SourceListRow {...source} snippet={null} />
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </ToolResultCard>
  )
}
