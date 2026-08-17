// apps/web/src/features/conversations/components/run-code-tool-row.tsx

import { FileCode2Icon, FileIcon } from "lucide-react"

import { FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { ToolResultCard } from "@/components/tool-ui/result-card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ConversationMarkdownContent } from "@/features/conversations/components/conversation-markdown-content"
import { FileEntityRow } from "@/features/conversations/components/file-entity-row"
import { ActivityStatusBadge } from "@/features/conversations/components/tool-activity-status"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { runCodeResult } from "@/features/conversations/native-tools/run-code"
import { formatBytes, pluralize } from "@/lib/format"

export function RunCodeToolRow({
  activity,
  defaultOpen,
}: {
  activity: ToolActivity
  defaultOpen: boolean
}) {
  if (activity.status === "running") {
    return (
      <FanOutSkeleton
        heading={
          <span className="flex items-center gap-2">
            <FileCode2Icon className="size-4" />
            Run Script
          </span>
        }
        label="Computing and preparing any requested files…"
      />
    )
  }
  const result = runCodeResult(activity.result)
  if (!result) {
    return null
  }
  const outputCount = result.outputs.length
  const updatedCount = result.outputs.filter((output) => output.updatedExisting).length
  const createdCount = outputCount - updatedCount
  const savedSummary = [
    createdCount > 0 ? `${String(createdCount)} created` : null,
    updatedCount > 0 ? `${String(updatedCount)} updated` : null,
  ]
    .filter((value): value is string => value !== null)
    .join(" · ")
  return (
    <ToolResultCard
      ariaLabel="Script result"
      defaultOpen={defaultOpen}
      details={[
        { label: "Provider", value: result.modelProvider },
        { label: "Model", value: result.model },
        {
          label: "Saved",
          value: savedSummary || `0 ${pluralize(outputCount, "output")}`,
        },
      ]}
      heading={
        <span className="flex items-center gap-2">
          <FileCode2Icon className="size-4" />
          Run Script
        </span>
      }
      trailing={<ActivityStatusBadge status={activity.status} />}
    >
      <div className="grid min-w-0 gap-4">
        <ConversationMarkdownContent content={result.result} />
        {result.outputs.length > 0 ? (
          <div className="divide-border border-border divide-y rounded-lg border px-2">
            {result.outputs.map((output) =>
              output.kind === "file" ? (
                <div key={output.reference.entityId}>
                  {output.updatedExisting ? (
                    <div className="flex items-center gap-2 px-1.5 pt-2">
                      <Badge variant="success">Updated</Badge>
                      {output.revisionNumber !== null ? (
                        <span className="text-muted-foreground text-xs">
                          Revision {String(output.revisionNumber)}
                        </span>
                      ) : null}
                    </div>
                  ) : null}
                  <FileEntityRow
                    file={{
                      contentType: output.mediaType,
                      fileId: output.reference.entityId,
                      name: output.name,
                      sizeBytes: output.sizeBytes,
                    }}
                  />
                </div>
              ) : (
                <div
                  className="flex min-w-0 items-center gap-3 px-1.5 py-2"
                  key={output.reference.entityId}
                >
                  <span className="bg-primary/8 text-primary flex size-8 shrink-0 items-center justify-center rounded-md">
                    <FileIcon className="size-4" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{output.name}</span>
                    <span className="text-muted-foreground block text-xs">
                      Artifact · {formatBytes(output.sizeBytes)}
                    </span>
                  </span>
                  <Button
                    render={
                      <a
                        aria-label={`Manage artifact ${output.name}`}
                        href={`/artifacts/${output.reference.entityId}`}
                      />
                    }
                    size="sm"
                    variant="outline"
                  >
                    Manage
                  </Button>
                </div>
              )
            )}
          </div>
        ) : null}
        {result.skippedOutputs.length > 0 ? (
          <div className="border-border bg-muted/20 rounded-lg border px-3 py-2">
            <div className="mb-1 flex items-center gap-2">
              <Badge variant="warning">Some outputs weren’t saved</Badge>
            </div>
            <ul className="text-muted-foreground list-disc space-y-1 pl-4 text-xs">
              {result.skippedOutputs.map((message, index) => (
                <li key={`${message}:${String(index)}`}>{message}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </ToolResultCard>
  )
}
