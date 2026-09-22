// apps/web/src/integrations/sharepoint/components/file-source.tsx

import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-types"
import { Button } from "@/components/ui/button"
import type { SharePointWriteArgs } from "@/integrations/sharepoint/lib/write-args"
import { formatBytes } from "@/lib/format"

export function SharePointFileSource({
  args,
  controls,
  disabled,
}: {
  args: SharePointWriteArgs
  controls: ToolApprovalDecisionControls
  disabled: boolean
}) {
  if (args.fieldKey === "parent") return null
  const details = args.sourceDetails?.id === args.source?.id ? args.sourceDetails : null
  const selectFileContent = () => {
    controls.onDecisionChange({
      decision: "pending",
      message: "",
      edits: { ...controls.decision.edits, content: null },
    })
  }
  const selectTextContent = () => {
    controls.onDecisionChange({
      decision: "pending",
      message: "",
      edits: { ...controls.decision.edits, source: null, content: args.content ?? "" },
    })
  }
  return (
    <div className="grid min-w-0 gap-2">
      {details ? (
        <div className="bg-muted rounded-md px-3 py-2 text-sm">
          <p className="font-medium wrap-break-word">{details.name}</p>
          <p className="text-muted-foreground wrap-break-word">
            {details.contentType} · {formatBytes(details.sizeBytes)}
          </p>
          <p className="text-muted-foreground mt-1 text-xs">
            Approval uses this reviewed version of the File.
          </p>
        </div>
      ) : args.source ? (
        <p className="text-muted-foreground text-sm">
          Review the selected File to check its type, size, and version.
        </p>
      ) : null}
      {controls.decision.decision === "pending" ? (
        <div className="flex flex-wrap gap-2">
          {args.source && args.content === null ? (
            <Button
              disabled={disabled || !controls.onReview}
              onClick={controls.onReview}
              size="sm"
              type="button"
              variant="outline"
            >
              Review selected File
            </Button>
          ) : null}
          {args.content !== null ? (
            <Button
              disabled={disabled}
              onClick={selectFileContent}
              size="sm"
              type="button"
              variant="ghost"
            >
              {args.source ? "Use selected File instead of text" : "Use a workspace File instead"}
            </Button>
          ) : (
            <Button
              disabled={disabled}
              onClick={selectTextContent}
              size="sm"
              type="button"
              variant="ghost"
            >
              Use text instead
            </Button>
          )}
        </div>
      ) : null}
    </div>
  )
}
