// apps/web/src/features/conversations/components/tool-friendly-blocks.tsx

import { ChevronRightIcon } from "lucide-react"

import { MessageMarkdown } from "@/features/conversations/components/message-markdown"
import { JsonBlock } from "@/features/conversations/components/tool-call-content-blocks"
import type { ResolvedToolField } from "@/features/conversations/tool-ui"

export function ToolFieldList({ fields }: { fields: ResolvedToolField[] }) {
  if (fields.length === 0) {
    return null
  }

  const inlineFields = fields.filter((field) => isInlineField(field))
  const blockFields = fields.filter((field) => !isInlineField(field))

  return (
    <div className="flex min-w-0 flex-col gap-2">
      {inlineFields.length > 0 ? (
        <dl className="bg-muted/30 grid min-w-0 grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 rounded-md px-3 py-2">
          {inlineFields.map((field) => (
            <InlineField field={field} key={field.key} />
          ))}
        </dl>
      ) : null}
      {blockFields.map((field) => (
        <BlockField field={field} key={field.key} />
      ))}
    </div>
  )
}

export function TechnicalDetails({ args, result }: { args: unknown; result: unknown }) {
  const hasArgs = args !== undefined && args !== null
  const hasResult = result !== undefined && result !== null
  if (!hasArgs && !hasResult) {
    return null
  }

  return (
    <details className="group/technical min-w-0">
      <summary className="text-muted-foreground hover:text-foreground flex cursor-pointer list-none items-center gap-1 text-xs">
        <ChevronRightIcon className="size-3 transition-transform group-open/technical:rotate-90" />
        Technical details
      </summary>
      <div className="mt-2 flex min-w-0 flex-col gap-3">
        {hasArgs ? <JsonBlock label="Input" value={args} /> : null}
        {hasResult ? <JsonBlock label="Output" value={result} /> : null}
      </div>
    </details>
  )
}

function isInlineField(field: ResolvedToolField) {
  return field.format !== "multiline" && field.format !== "markdown" && field.value.length <= 120
}

function InlineField({ field }: { field: ResolvedToolField }) {
  return (
    <>
      <dt className="text-muted-foreground text-xs font-medium whitespace-nowrap">{field.label}</dt>
      <dd className="text-foreground wrap-break-words min-w-0 text-xs leading-relaxed">
        {field.value}
      </dd>
    </>
  )
}

function BlockField({ field }: { field: ResolvedToolField }) {
  return (
    <div className="min-w-0">
      <p className="text-muted-foreground mb-1 text-xs font-medium">{field.label}</p>
      {field.format === "markdown" ? (
        <div className="bg-muted/30 rounded-md px-3 py-2 text-sm">
          <MessageMarkdown content={field.value} />
        </div>
      ) : (
        <pre className="bg-muted/50 max-h-80 overflow-auto rounded-md p-2 text-xs leading-relaxed whitespace-pre-wrap">
          {field.value}
        </pre>
      )}
    </div>
  )
}
