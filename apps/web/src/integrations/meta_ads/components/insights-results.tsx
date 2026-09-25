// apps/web/src/integrations/meta_ads/components/insights-results.tsx

import { EmptyResult } from "@/components/tool-ui/empty-result"
import { DataTable } from "@/components/ui/data-table"
import type { MetaAdsInsights } from "@/integrations/meta_ads/lib/insights-model"

export function MetaAdsInsightsResults({
  report,
  externalId,
}: {
  report: MetaAdsInsights
  externalId: string
}) {
  return (
    <div className="grid min-w-0 gap-3">
      <p className="text-muted-foreground text-xs">
        {report.currency || "Currency unavailable"} ·{" "}
        {report.timezone || "Account time zone unavailable"}
        {report.mode === "background" ? " · Prepared as a background report" : null}
      </p>
      {report.notes.length > 0 ? (
        <ul className="text-muted-foreground grid gap-1 text-xs">
          {report.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
      {report.rows.length > 0 ? (
        <DataTable
          pageSize={25}
          columns={report.columns}
          rows={report.rows}
          exportFilename={`meta-ads-${externalId}-insights.csv`}
          truncationNote={report.truncationNote}
        />
      ) : (
        <EmptyResult>No report rows returned.</EmptyResult>
      )}
    </div>
  )
}
