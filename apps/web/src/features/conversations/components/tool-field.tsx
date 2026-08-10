// apps/web/src/features/conversations/components/tool-field.tsx

import { useId, type ReactNode } from "react"

import { fieldLabelClass, readOnlyFieldWellClass } from "@/components/tool-ui/field-styles"
import { ToolFieldValue } from "@/components/tool-ui/field-value"
import { MarkdownContent } from "@/components/markdown/markdown-content"
import type { ResolvedToolField } from "@/features/conversations/tool-ui"
import { cn } from "@/lib/utils"

const FULL_WIDTH_FORMATS = new Set<ResolvedToolField["format"]>([
  "list",
  "markdown",
  "multiline",
  "url",
])

export function ToolField({
  children,
  field,
  urlAction = false,
}: {
  children?: ReactNode
  field: ResolvedToolField
  urlAction?: boolean
}) {
  const labelId = useId()
  const hasCustomContent = children !== undefined
  // Records render their own bordered surface, so they skip the well fill.
  const rendersOwnSurface =
    field.format === "records" && field.records !== undefined && field.records.length > 0
  const spansFullWidth =
    hasCustomContent ||
    rendersOwnSurface ||
    FULL_WIDTH_FORMATS.has(field.format) ||
    field.value.length > 120
  const scrolls =
    field.format === "markdown" || field.format === "multiline" || field.value.length > 120

  return (
    <div className={cn("flex min-w-0 flex-col gap-1", spansFullWidth && "sm:col-span-2")}>
      <p className={fieldLabelClass} data-slot="tool-field-label" id={labelId}>
        {field.label}
      </p>
      <div
        aria-labelledby={labelId}
        className={cn(
          rendersOwnSurface
            ? "min-w-0"
            : [
                readOnlyFieldWellClass,
                "text-foreground",
                scrolls && "max-h-80 overflow-auto",
                field.format !== "markdown" && "wrap-break-word whitespace-pre-wrap",
              ]
        )}
        data-slot="tool-field-well"
      >
        {hasCustomContent ? (
          children
        ) : (
          <ToolFieldValue
            field={field}
            renderMarkdown={(value) => <MarkdownContent content={value} />}
            urlAction={urlAction}
          />
        )}
      </div>
    </div>
  )
}

export function ToolFieldGrid({
  fields,
  urlActions = false,
}: {
  fields: ResolvedToolField[]
  urlActions?: boolean
}) {
  if (fields.length === 0) {
    return null
  }

  return (
    <div className="grid min-w-0 gap-3 sm:grid-cols-2">
      {fields.map((field) => (
        <ToolField field={field} key={field.key} urlAction={urlActions} />
      ))}
    </div>
  )
}
