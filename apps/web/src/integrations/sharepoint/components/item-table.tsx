// apps/web/src/integrations/sharepoint/components/item-table.tsx

import { EmptyResult } from "@/components/tool-ui/empty-result"
import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"
import { pluralize } from "@/lib/format"

const COLUMNS: DataColumn[] = [
  { key: "name", label: "Name", kind: "text", width: 240 },
  { key: "kind", label: "Kind", kind: "badge", width: 100 },
  { key: "size_bytes", label: "Size (bytes)", kind: "number" },
  { key: "modified_at", label: "Modified", kind: "datetime" },
  { key: "web_url", label: "Open in SharePoint", kind: "link" },
  { key: "path", label: "Path", kind: "text" },
  { key: "content_type", label: "Content type", kind: "text" },
]

export function SharePointItemTable({ rows, hasMore }: { rows: DataRow[]; hasMore: boolean }) {
  const more = hasMore ? "More items are available in this folder." : null
  if (rows.length === 0) {
    return <EmptyResult>{more ?? "No files or folders found."}</EmptyResult>
  }
  return (
    <DataTable
      columns={COLUMNS}
      exportFilename="sharepoint-items.csv"
      header={
        <p className="text-muted-foreground text-xs">
          {String(rows.length)} {pluralize(rows.length, "item", "items")}
        </p>
      }
      pageSize={25}
      rows={rows}
      truncationNote={more}
    />
  )
}
