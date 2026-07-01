// apps/web/src/features/conversations/components/markdown-table.tsx

import { isValidElement, memo, useCallback, useMemo, type ReactNode } from "react"
import { CheckIcon, CopyIcon, DownloadIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { useClipboardCopy } from "@/hooks/use-clipboard-copy"
import { reactNodeToText } from "@/lib/react-node"
import { cn } from "@/lib/utils"

type ExtractedTable = {
  headers: string[]
  rows: string[][]
}

export const MarkdownTable = memo(function MarkdownTable({ children }: { children?: ReactNode }) {
  const extracted = useMemo(() => extractTable(children), [children])
  const { copied, copy } = useClipboardCopy()
  const hasContent = extracted.headers.length > 0 || extracted.rows.length > 0

  const handleCopy = useCallback(() => {
    void copy(toTsv(extracted))
  }, [copy, extracted])

  return (
    <div className="my-4">
      {hasContent && (
        <div className="flex items-center justify-end gap-1 pb-1.5">
          <Button
            aria-label={copied ? "Copied table" : "Copy table"}
            size="icon-xs"
            type="button"
            variant="ghost"
            onClick={handleCopy}
          >
            {copied ? <CheckIcon /> : <CopyIcon />}
          </Button>
          <Button
            aria-label="Download table CSV"
            size="icon-xs"
            type="button"
            variant="ghost"
            onClick={() => {
              downloadCsv(extracted)
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

function toCsv({ headers, rows }: ExtractedTable): string {
  return [
    headers.map(escapeCsvCell).join(","),
    ...rows.map((row) => row.map(escapeCsvCell).join(",")),
  ]
    .filter((line) => line.length > 0)
    .join("\r\n")
}

function toTsv({ headers, rows }: ExtractedTable): string {
  const sanitize = (cell: string) => cell.replace(/\t/g, " ").replace(/\r?\n/g, " ")
  return [headers.map(sanitize).join("\t"), ...rows.map((row) => row.map(sanitize).join("\t"))]
    .filter((line) => line.length > 0)
    .join("\n")
}

function escapeCsvCell(cell: string): string {
  if (/[",\r\n]/.test(cell)) {
    return `"${cell.replace(/"/g, '""')}"`
  }
  return cell
}

function downloadCsv(extracted: ExtractedTable): void {
  const blob = new Blob([toCsv(extracted)], { type: "text/csv;charset=utf-8" })
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = "conversation-table.csv"
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}
