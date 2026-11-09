// apps/web/src/integrations/google_ads/components/targeting-search-table.tsx

import { DataTable, type DataColumn } from "@/components/ui/data-table"
import {
  reachText,
  type TargetingSearchResult,
} from "@/integrations/google_ads/lib/targeting-search"

const LOCATION_COLUMNS: DataColumn[] = [
  { key: "name", label: "Location", kind: "text" },
  { key: "type", label: "Type", kind: "text" },
  { key: "region", label: "Region", kind: "text" },
  { key: "reach", label: "Reach", kind: "text", align: "right" },
  { key: "key", label: "Key", kind: "id", hidden: true },
]

const LANGUAGE_COLUMNS: DataColumn[] = [
  { key: "name", label: "Language", kind: "text" },
  { key: "key", label: "Key", kind: "id", hidden: true },
]

/** One table of what the search found, with columns that follow the kind. */
export function TargetingSearchTable({
  accountId,
  result,
}: {
  accountId: string
  result: TargetingSearchResult
}) {
  const languages = result.options.every((option) => option.kind === "language")
  return (
    <DataTable
      columns={languages ? LANGUAGE_COLUMNS : LOCATION_COLUMNS}
      exportFilename={`google-ads-${accountId}-targeting.csv`}
      pageSize={25}
      rows={result.options.map((option) => ({
        key: option.key,
        name: option.name,
        reach: reachText(option.reach),
        region: option.region ?? "—",
        type: option.targetType ?? "—",
      }))}
      truncationNote={result.truncated ? "Google has more matches. Search more precisely." : null}
    />
  )
}
