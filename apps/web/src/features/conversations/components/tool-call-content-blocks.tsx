// apps/web/src/features/conversations/components/tool-call-content-blocks.tsx

import { safeJsonPreview } from "@/features/conversations/message-parts"

export function JsonBlock({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="min-w-0">
      <p className="text-muted-foreground mb-1 text-xs font-medium">{label}</p>
      <pre className="bg-muted/40 max-h-64 overflow-auto rounded-md p-2 text-xs leading-relaxed whitespace-pre-wrap">
        {safeJsonPreview(value)}
      </pre>
    </div>
  )
}
