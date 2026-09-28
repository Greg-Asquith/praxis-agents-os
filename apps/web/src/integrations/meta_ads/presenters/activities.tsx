// apps/web/src/integrations/meta_ads/presenters/activities.tsx

import { EmptyResult } from "@/components/tool-ui/empty-result"
import { DataTable, type DataColumn } from "@/components/ui/data-table"
import { parseMetaAdsActivities } from "@/integrations/meta_ads/lib/read-models"
import { metaAdsProvider } from "@/integrations/meta_ads/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"
import { compactDetails, listDetail, stringArg } from "@/integrations/tool-details"
import { titleCaseToken } from "@/lib/format"

const columns: DataColumn[] = [
  { key: "event_time", label: "Time", kind: "datetime" },
  { key: "change", label: "Change", kind: "text" },
  { key: "object_name", label: "Object", kind: "text" },
  { key: "object_type", label: "Object type", kind: "text" },
  { key: "actor_name", label: "Changed by", kind: "text" },
  { key: "old_value", label: "Old value", kind: "text" },
  { key: "new_value", label: "New value", kind: "text" },
  { key: "object_id", label: "Object ID", kind: "id" },
]

export const metaAdsActivitiesPresenter = defineIntegrationReadPresenter(metaAdsProvider, {
  ariaLabel: "Meta Ads change history",
  emptyLabel: "No Meta Ads accounts were queried.",
  heading: "List Meta Ads changes",
  progressLabel: "Loading Meta Ads changes…",
  tool: "meta_ads_list_activities",
  details: (args) => {
    const since = stringArg(args, "since")
    const until = stringArg(args, "until")
    return compactDetails([
      since && until ? { label: "Range", value: `${since} → ${until}` } : null,
      listDetail(args, "object_ids", "Object IDs"),
    ])
  },
  parseResult: parseMetaAdsActivities,
  render: (result, entry) => (
    <div className="grid min-w-0 gap-3">
      <ul className="text-muted-foreground grid gap-1 text-xs">
        <li>Dates use the {result.timezone_name} time zone.</li>
        {result.events.some((event) => event.old_value !== null || event.new_value !== null) ? (
          <li>
            Old and new values appear as Meta reports them. Amounts can be in the smallest currency
            unit, such as cents.
          </li>
        ) : null}
        {result.window_note ? <li>{result.window_note}</li> : null}
      </ul>
      {result.events.length > 0 ? (
        <DataTable
          columns={columns}
          rows={result.events.map((event) => ({
            ...event,
            change:
              event.translated_event_type ??
              (event.event_type ? titleCaseToken(event.event_type, event.event_type) : null),
            object_type: event.object_type
              ? titleCaseToken(event.object_type.toLowerCase(), event.object_type)
              : null,
          }))}
          pageSize={25}
          exportFilename={`meta-ads-${entry.externalId}-changes.csv`}
        />
      ) : (
        <EmptyResult>
          {result.truncated
            ? "No changes were returned before the retrieval limit."
            : "No changes were found in this date range."}
        </EmptyResult>
      )}
    </div>
  ),
})
