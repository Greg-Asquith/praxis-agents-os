// apps/web/src/components/tool-ui/field-value.tsx

import { ExternalLinkIcon } from "lucide-react"
import type { ReactNode } from "react"

import type { ResolvedRecordRow, ResolvedToolField } from "@/components/tool-ui/field-resolution"
import { uniqueRowKeys } from "@/components/tool-ui/records-field-values"
import { buttonVariants } from "@/components/ui/button"
import { truncateText } from "@/lib/format"

const URL_LABEL_LIMIT = 80

export function ToolFieldValue({
  field,
  renderMarkdown,
  urlAction = false,
}: {
  field: ResolvedToolField
  renderMarkdown?: (value: string) => ReactNode
  urlAction?: boolean
}) {
  if (field.format === "url") {
    if (urlAction) {
      return (
        <a
          className={buttonVariants({ variant: "outline", size: "sm" })}
          href={field.value}
          rel="noreferrer"
          target="_blank"
        >
          <ExternalLinkIcon data-icon="inline-start" />
          Open {field.label}
        </a>
      )
    }

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

  if (field.format === "keyvalue" && field.entries && field.entries.length > 0) {
    return (
      <dl className="divide-border/60 -mx-2.5 -my-1 divide-y">
        {field.entries.map((entry) => (
          <div
            className="grid min-w-0 gap-1 px-2.5 py-2 sm:grid-cols-[minmax(7rem,0.4fr)_minmax(0,1fr)] sm:gap-3"
            key={entry.key}
          >
            <dt className="text-foreground/75 truncate text-xs font-medium">{entry.key}</dt>
            <dd className="min-w-0 wrap-break-word">{entry.value}</dd>
          </div>
        ))}
      </dl>
    )
  }

  if (field.format === "records" && field.records) {
    if (field.records.length === 0) {
      return field.value
    }
    const columns = field.records[0]?.cells ?? []
    const rows = keyedResolvedRows(field.records)
    return (
      <div className="-mx-2.5 -my-1 max-h-80 overflow-auto">
        <div className="text-muted-foreground border-border/60 border-b px-2.5 py-1.5 text-xs font-medium">
          {field.value}
        </div>
        <table className="w-full min-w-max border-separate border-spacing-0 text-left text-xs">
          <thead className="bg-muted/80 text-muted-foreground sticky top-0">
            <tr>
              {columns.map((cell) => (
                <th className="border-border/60 border-b px-2.5 py-1.5 font-medium" key={cell.key}>
                  {cell.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(({ key, row }) => (
              <tr className="[&:not(:last-child)>td]:border-b" key={key}>
                {row.cells.map((cell) => (
                  <td
                    className="border-border/60 min-w-32 px-2.5 py-2 wrap-break-word"
                    key={cell.key}
                  >
                    {cell.value}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  if (field.format === "markdown" && renderMarkdown) {
    return renderMarkdown(field.value)
  }

  return field.value
}

function keyedResolvedRows(records: ResolvedRecordRow[]) {
  const keys = uniqueRowKeys(records.map((row) => row.cells.map((cell) => cell.value)))
  return records.map((row, index) => ({ key: keys[index] ?? "", row }))
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
