// apps/web/src/features/conversations/components/tool-field.tsx

import { useId, type ReactNode } from "react"

import { MessageMarkdown } from "@/features/conversations/components/message-markdown"
import type { ResolvedToolField } from "@/features/conversations/tool-ui"
import { truncateText } from "@/lib/format"
import { cn } from "@/lib/utils"

const FULL_WIDTH_FORMATS = new Set<ResolvedToolField["format"]>([
  "list",
  "markdown",
  "multiline",
  "url",
])
const URL_LABEL_LIMIT = 80

export const toolFieldLabelClass = "text-muted-foreground text-sm leading-none font-medium"
export const toolFieldWellClass =
  "min-h-8 w-full min-w-0 rounded-lg border px-2.5 py-1 text-sm leading-relaxed"

export function ToolField({ children, field }: { children?: ReactNode; field: ResolvedToolField }) {
  const labelId = useId()
  const hasCustomContent = children !== undefined
  const spansFullWidth =
    hasCustomContent || FULL_WIDTH_FORMATS.has(field.format) || field.value.length > 120
  const scrolls =
    field.format === "markdown" || field.format === "multiline" || field.value.length > 120

  return (
    <div className={cn("flex min-w-0 flex-col gap-1", spansFullWidth && "sm:col-span-2")}>
      <p className={toolFieldLabelClass} data-slot="tool-field-label" id={labelId}>
        {field.label}
      </p>
      <div
        aria-labelledby={labelId}
        className={cn(
          toolFieldWellClass,
          "border-input bg-muted/40 text-foreground",
          scrolls && "max-h-80 overflow-auto",
          field.format !== "markdown" && "wrap-break-word whitespace-pre-wrap"
        )}
        data-slot="tool-field-well"
      >
        {hasCustomContent ? children : <ToolFieldValue field={field} />}
      </div>
    </div>
  )
}

export function ToolFieldGrid({ fields }: { fields: ResolvedToolField[] }) {
  if (fields.length === 0) {
    return null
  }

  return (
    <div className="grid min-w-0 gap-3 sm:grid-cols-2">
      {fields.map((field) => (
        <ToolField field={field} key={field.key} />
      ))}
    </div>
  )
}

function ToolFieldValue({ field }: { field: ResolvedToolField }) {
  if (field.format === "url") {
    return (
      <a
        className="text-link hover:text-primary focus-visible:ring-ring/50 inline-block max-w-full rounded-sm underline underline-offset-2 outline-none focus-visible:ring-3"
        href={field.value}
        rel="noreferrer"
        target="_blank"
      >
        {toolUrlLabel(field.value)}
      </a>
    )
  }

  if (field.format === "list" && field.items && field.items.length > 0) {
    return (
      <div className="flex min-w-0 flex-wrap gap-1.5">
        {field.items.map((item, index) => (
          <span
            className="bg-muted rounded-md px-2 py-0.5 text-xs"
            key={`${item}:${String(index)}`}
          >
            {item}
          </span>
        ))}
      </div>
    )
  }

  if (field.format === "markdown") {
    return <MessageMarkdown content={field.value} />
  }

  return field.value
}

function toolUrlLabel(value: string): string {
  try {
    const url = new URL(value)
    const path = `${url.pathname}${url.search}${url.hash}`
    const label = path === "/" ? url.host : `${url.host}${path}`
    return truncateText(label, URL_LABEL_LIMIT, "…")
  } catch {
    return truncateText(value, URL_LABEL_LIMIT, "…")
  }
}
