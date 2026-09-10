// apps/web/src/integrations/google_search_console/components/sitemaps-table.tsx

import { EmptyResult } from "@/components/tool-ui/empty-result"
import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"
import { filenameStem } from "@/lib/format"

const COLUMNS: DataColumn[] = [
  { key: "path", kind: "link", label: "Sitemap", width: "auto" },
  { key: "type", kind: "badge", label: "Type" },
  { key: "last_submitted", kind: "datetime", label: "Submitted" },
  { key: "pending", kind: "status", label: "Status" },
  { key: "warnings", kind: "number", label: "Warnings", isMetric: true },
  { key: "errors", kind: "number", label: "Errors", isMetric: true },
  { key: "submitted_url_count", kind: "number", label: "Submitted URLs", isMetric: true },
]

export function SitemapsTable({ externalId, rows }: { externalId: string; rows: DataRow[] }) {
  return rows.length > 0 ? (
    <DataTable
      columns={COLUMNS}
      exportFilename={`search-console-${filenameStem(externalId, "site")}-sitemaps.csv`}
      rows={rows}
    />
  ) : (
    <EmptyResult>No submitted sitemaps were found.</EmptyResult>
  )
}
