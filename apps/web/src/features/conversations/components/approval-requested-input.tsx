// apps/web/src/features/conversations/components/approval-requested-input.tsx

import { safeJsonPreview } from "@/features/conversations/message-parts"

const REQUEST_INPUT_COLLAPSE_LIMIT = 720

export function ApprovalRequestedInput({ value }: { value: unknown }) {
  const preview = safeJsonPreview(value)
  const isLong = isLongJsonPreview(preview)

  return (
    <div className="bg-muted/20 rounded-md border p-3">
      <p className="text-sm font-medium">Requested input</p>
      {isLong ? (
        <details className="mt-2">
          <summary className="text-muted-foreground hover:text-foreground cursor-pointer text-sm">
            Show requested input
          </summary>
          <JsonPreview value={preview} />
        </details>
      ) : (
        <JsonPreview value={preview} />
      )}
    </div>
  )
}

function JsonPreview({ value }: { value: string }) {
  return (
    <pre className="bg-background text-muted-foreground mt-2 max-h-48 overflow-auto rounded-md border p-2 text-xs leading-relaxed whitespace-pre-wrap">
      {value}
    </pre>
  )
}

function isLongJsonPreview(value: string) {
  return value.length > REQUEST_INPUT_COLLAPSE_LIMIT || value.split("\n").length > 16
}
