// apps/web/src/integrations/meta_ads/presenters/custom-conversions.tsx

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
  { key: "availability", label: "Availability", kind: "status" },
  { key: "description", label: "Description", kind: "text" },
  { key: "id", label: "Conversion ID", kind: "id" },
]

export const metaAdsCustomConversionsPresenter = defineIntegrationReadPresenter(metaAdsProvider, {
  ariaLabel: "Meta Ads custom conversions",
  emptyLabel: "No Meta Ads accounts were queried.",
  heading: "List Meta Ads custom conversions",
  progressLabel: "Loading Meta Ads custom conversions…",
  tool: "meta_ads_list_custom_conversions",
  parseResult: parseMetaAdsConversions,
  render: (result, entry) => (
    <div className="grid min-w-0 gap-3">
      {result.notes.length > 0 ? (
        <ul className="text-muted-foreground grid gap-1 text-xs">
          {result.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
      {result.conversions.length > 0 ? (
        <DataTable
          columns={columns}
          rows={result.conversions.map((conversion) => ({
            ...conversion,
            name: conversion.name ?? UNRESOLVED_CONVERSION_NAME,
            availability: availability(conversion),
          }))}
          pageSize={25}
          exportFilename={`meta-ads-${entry.externalId}-custom-conversions.csv`}
          truncationNote={result.truncated ? "More custom conversions are available." : null}
        />
      ) : (
        <EmptyResult>No custom conversions were returned.</EmptyResult>
      )}
    </div>
  ),
})

function availability(conversion: MetaAdsConversion): string {
  if (conversion.is_archived) return "Archived"
  if (conversion.is_unavailable) return "Unavailable"
  if (conversion.is_archived === false && conversion.is_unavailable === false) return "Available"
  return "Unknown"
}
