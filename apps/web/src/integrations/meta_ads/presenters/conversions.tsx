// apps/web/src/integrations/meta_ads/presenters/conversions.tsx

import { EmptyResult } from "@/components/tool-ui/empty-result"
import { DataTable, type DataColumn } from "@/components/ui/data-table"
import {
  parseMetaAdsConversions,
  UNRESOLVED_CONVERSION_NAME,
  type MetaAdsConversion,
} from "@/integrations/meta_ads/lib/read-models"
import { metaAdsProvider } from "@/integrations/meta_ads/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"

const columns: DataColumn[] = [
  { key: "name", label: "Name", kind: "text" },
  { key: "type", label: "Type", kind: "text" },
  { key: "recent_conversions", label: "Recent conversions", kind: "number" },
  { key: "availability", label: "Availability", kind: "status" },
  { key: "description", label: "Description", kind: "text" },
  { key: "id", label: "Conversion ID", kind: "id" },
]

export const metaAdsConversionsPresenter = defineIntegrationReadPresenter(metaAdsProvider, {
  ariaLabel: "Meta Ads Conversion Actions",
  emptyLabel: "No Meta Ads accounts were queried.",
  heading: "List Meta Ads conversion actions",
  progressLabel: "Loading Meta Ads conversion actions…",
  tool: "meta_ads_list_conversions",
  parseResult: parseMetaAdsConversions,
  render: (result, entry) => (
    <div className="grid min-w-0 gap-3">
      <ul className="text-muted-foreground grid gap-1 text-xs">
        {result.recent_since && result.recent_until ? (
          <li>
            Recent conversions run from {result.recent_since} to {result.recent_until}. Custom
            events appear only when ads recorded them in that period.
          </li>
        ) : null}
        {result.notes.map((note) => (
          <li key={note}>{note}</li>
        ))}
      </ul>
      {result.conversions.length > 0 ? (
        <DataTable
          columns={columns}
          rows={result.conversions.map((conversion) => ({
            ...conversion,
            name: conversion.name ?? UNRESOLVED_CONVERSION_NAME,
            type: conversion.kind === "custom_event" ? "Custom event" : "Custom conversion",
            availability: availability(conversion),
          }))}
          pageSize={25}
          exportFilename={`meta-ads-${entry.externalId}-conversions.csv`}
          truncationNote={result.truncated ? "More custom conversions are available." : null}
        />
      ) : (
        <EmptyResult>No custom conversions or custom events were returned.</EmptyResult>
      )}
    </div>
  ),
})

function availability(conversion: MetaAdsConversion): string | null {
  if (conversion.kind === "custom_event") return null
  if (conversion.is_archived) return "Archived"
  if (conversion.is_unavailable) return "Unavailable"
  if (conversion.is_archived === false && conversion.is_unavailable === false) return "Available"
  return "Unknown"
}
