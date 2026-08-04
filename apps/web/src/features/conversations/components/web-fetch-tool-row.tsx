// apps/web/src/features/conversations/components/web-fetch-tool-row.tsx

import { LinkIcon } from "lucide-react"

import { MarkdownContent } from "@/components/markdown/markdown-content"
import { FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { ToolResultCard } from "@/components/tool-ui/result-card"
import { SourceListRow } from "@/components/tool-ui/source"
import { Badge } from "@/components/ui/badge"
import { webFetchResult, webFetchUrl } from "@/features/conversations/components/web-fetch-result"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { pluralize } from "@/lib/format"

export function WebFetchToolRow({
  activity,
  defaultOpen = false,
}: {
  activity: ToolActivity
  defaultOpen?: boolean
}) {
  if (activity.status === "running") {
    const url = webFetchUrl(activity.args)
    return url ? (
      <FanOutSkeleton
        heading={<WebFetchHeading />}
        label={`Fetching ${url}…`}
        summary={`URL: ${url}`}
      />
    ) : null
  }

  if (activity.status !== "completed") {
    return null
  }
  const result = webFetchResult(activity.result)
  if (!result) {
    return null
  }

  const sourceCount = result.sources.length
  const details = [
    { label: "URL", value: result.url },
    { label: "Sources", value: `${String(sourceCount)} ${pluralize(sourceCount, "Source")}` },
    { label: "Provider", value: result.provider },
    { label: "Model", value: result.model },
  ]
  return (
    <ToolResultCard
      ariaLabel={`Fetched page content from ${result.url}`}
      defaultOpen={defaultOpen}
      details={details}
      heading={<WebFetchHeading />}
      trailing={<Badge variant="success">Done</Badge>}
    >
      <div className="grid min-w-0 gap-4">
        <div className="grid min-w-0 gap-2">
          <p className="text-muted-foreground text-xs font-medium">Fetched Page Content</p>
          <div
            aria-label="Fetched page content"
            className="border-input bg-muted/40 max-h-[min(32rem,60vh)] min-w-0 overflow-y-auto overscroll-contain rounded-md border px-3 py-2.5"
          >
            <MarkdownContent content={result.content} />
          </div>
        </div>
        {sourceCount > 0 ? (
          <div className="grid min-w-0 gap-2">
            <p className="text-muted-foreground text-xs font-medium">Sources</p>
            <div aria-label="Fetched page sources" className="grid min-w-0 gap-2" role="list">
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

function WebFetchHeading() {
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <LinkIcon className="text-muted-foreground size-4 shrink-0" />
      <span>Web Fetch</span>
    </span>
  )
}
