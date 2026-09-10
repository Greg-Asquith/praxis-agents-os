// apps/web/src/integrations/google_search_console/components/search-analytics-results.tsx

import { EmptyResult } from "@/components/tool-ui/empty-result"
import { DataTable } from "@/components/ui/data-table"
import type { SearchAnalyticsReport } from "@/integrations/google_search_console/lib/search-analytics-model"
import { filenameStem } from "@/lib/format"

export function SearchAnalyticsResults({
  externalId,
  report,
}: {
  externalId: string
  report: SearchAnalyticsReport
}) {
  return report.rows.length > 0 ? (
    <DataTable
      columns={report.columns}
      exportFilename={`search-console-${filenameStem(externalId, "site")}-analytics.csv`}
      rows={report.rows}
      truncationNote={report.truncated ? report.truncationNote : null}
    />
  ) : (
    <EmptyResult>No search performance rows returned.</EmptyResult>
  )
}
