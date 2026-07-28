// apps/web/src/components/markdown-table.tsx

import { isValidElement, memo, useCallback, useMemo, type ReactNode } from "react"
import { CheckIcon, CopyIcon, DownloadIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { useClipboardCopy } from "@/hooks/use-clipboard-copy"
import { reactNodeToText } from "@/lib/react-node"
import { downloadTableCsv, tableToTsv, type ExportTable } from "@/lib/table-export"
import { cn } from "@/lib/utils"

type ExtractedTable = ExportTable

export const MarkdownTable = memo(function MarkdownTable({ children }: { children?: ReactNode }) {
  const extracted = useMemo(() => extractTable(children), [children])
  const { copied, copy } = useClipboardCopy()
  const hasContent = extracted.headers.length > 0 || extracted.rows.length > 0

  const handleCopy = useCallback(() => {
    void copy(tableToTsv(extracted))
  }, [copy, extracted])

  return (
    <div className="my-4">
      {hasContent && (
        <div className="flex items-center justify-end gap-1 pb-1.5">
          <Button
            aria-label={copied ? "Copied Table" : "Copy Table"}
            size="icon-xs"
            type="button"
            variant="ghost"
            onClick={handleCopy}
          >
            {copied ? <CheckIcon /> : <CopyIcon />}
          </Button>
          <Button
            aria-label="Download Table CSV"
            size="icon-xs"
            type="button"
            variant="ghost"
            onClick={() => {
              downloadTableCsv(extracted)
            }}
          >
            <DownloadIcon />
          </Button>
        </div>
      )}
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full min-w-max border-collapse text-sm">{children}</table>
      </div>
    </div>
  )
})

export function MarkdownTableHead({ children, ...props }: React.ComponentProps<"thead">) {
  return (
    <thead className="bg-muted/70" {...props}>
      {children}
    </thead>
  )
}

export function MarkdownTableRow({ children, className, ...props }: React.ComponentProps<"tr">) {
  return (
    <tr className={cn("even:bg-muted/30 border-b last:border-b-0", className)} {...props}>
      {children}
    </tr>
  )
}

export function MarkdownTableHeader({ children, className, ...props }: React.ComponentProps<"th">) {
  return (
    <th
      className={cn(
        "border-r px-3 py-2 text-left align-top font-medium last:border-r-0",
        className
      )}
      {...props}
    >
      {children}
    </th>
  )
}

export function MarkdownTableCell({ children, className, ...props }: React.ComponentProps<"td">) {
  return (
    <td className={cn("border-r px-3 py-2 align-top last:border-r-0", className)} {...props}>
      {children}
    </td>
  )
}

function extractTable(children: ReactNode): ExtractedTable {
  const headerCells: React.ReactElement[] = []
  findElementsByTag(children, "th", headerCells)

  const rowElements: React.ReactElement[] = []
  findElementsByTag(children, "tr", rowElements)

  const rows: string[][] = []
  for (const row of rowElements) {
    const dataCells: React.ReactElement[] = []
    const props = row.props as { children?: ReactNode }
    findElementsByTag(props.children, "td", dataCells)
    if (dataCells.length === 0) {
      continue
    }

    rows.push(
      dataCells.map((cell) => {
        const cellProps = cell.props as { children?: ReactNode }
        return reactNodeToText(cellProps.children).trim()
      })
    )
  }

  return {
    headers: headerCells.map((cell) => {
      const props = cell.props as { children?: ReactNode }
      return reactNodeToText(props.children).trim()
    }),
    rows,
  }
}

function findElementsByTag(node: ReactNode, tag: string, out: React.ReactElement[]): void {
  if (node === null || node === undefined || typeof node === "boolean") {
    return
  }

  if (Array.isArray(node)) {
    for (const child of node as ReactNode[]) {
      findElementsByTag(child, tag, out)
    }
    return
  }

  if (!isValidElement(node)) {
    return
  }

  if (typeof node.type === "string" && node.type === tag) {
    out.push(node)
    return
  }

  const props = node.props as { children?: ReactNode }
  findElementsByTag(props.children, tag, out)
}
