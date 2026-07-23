// apps/web/src/lib/table-export.ts

export type ExportTable = {
  headers: string[]
  rows: string[][]
}

export function tableToCsv({ headers, rows }: ExportTable): string {
  return [
    headers.map(escapeCsvCell).join(","),
    ...rows.map((row) => row.map(escapeCsvCell).join(",")),
  ]
    .filter((line) => line.length > 0)
    .join("\r\n")
}

export function tableToTsv({ headers, rows }: ExportTable): string {
  const sanitize = (cell: string) => cell.replace(/\t/g, " ").replace(/\r?\n/g, " ")
  return [headers.map(sanitize).join("\t"), ...rows.map((row) => row.map(sanitize).join("\t"))]
    .filter((line) => line.length > 0)
    .join("\n")
}

export function downloadTableCsv(table: ExportTable, filename = "conversation-table.csv"): void {
  const blob = new Blob([tableToCsv(table)], { type: "text/csv;charset=utf-8" })
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

function escapeCsvCell(cell: string): string {
  if (/[",\r\n]/.test(cell)) {
    return `"${cell.replace(/"/g, '""')}"`
  }
  return cell
}
