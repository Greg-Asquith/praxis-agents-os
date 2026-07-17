// apps/web/src/features/conversations/components/tool-friendly-blocks.tsx

import { ChevronRightIcon } from "lucide-react"

import { JsonBlock } from "@/features/conversations/components/tool-call-content-blocks"

export function TechnicalDetails({ args, result }: { args: unknown; result: unknown }) {
  const hasArgs = args !== undefined && args !== null
  const hasResult = result !== undefined && result !== null
  if (!hasArgs && !hasResult) {
    return null
  }

  return (
    <details className="group/technical min-w-0">
      <summary className="text-muted-foreground hover:bg-muted/60 hover:text-foreground -mx-1.5 flex cursor-pointer list-none items-center gap-1 rounded-md px-1.5 py-1 text-xs transition-colors">
        <ChevronRightIcon className="size-3 transition-transform group-open/technical:rotate-90" />
        Technical Details
      </summary>
      <div className="mt-2 flex min-w-0 flex-col gap-3">
        {hasArgs ? <JsonBlock label="Input" value={args} /> : null}
        {hasResult ? <JsonBlock label="Output" value={result} /> : null}
      </div>
    </details>
  )
}
