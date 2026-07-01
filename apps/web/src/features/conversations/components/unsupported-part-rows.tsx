// apps/web/src/features/conversations/components/unsupported-part-rows.tsx

import type { ParsedConversationMessage } from "@/features/conversations/message-parts"

export function UnsupportedPartRows({ message }: { message: ParsedConversationMessage }) {
  if (message.unsupportedParts.length === 0) {
    return null
  }

  return (
    <div className="flex flex-col gap-2">
      {message.unsupportedParts.map((part) => (
        <details
          key={part.id}
          className="border-border/80 bg-muted/20 rounded-lg border border-dashed px-3 py-2 text-sm"
        >
          <summary className="text-muted-foreground hover:text-foreground cursor-pointer font-medium">
            {part.label}
          </summary>
          <pre className="mt-2 max-h-64 overflow-auto text-xs whitespace-pre-wrap">
            {part.preview}
          </pre>
        </details>
      ))}
    </div>
  )
}
