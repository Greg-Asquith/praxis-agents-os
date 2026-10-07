// apps/web/src/integrations/meta_ads/components/asset-section.tsx

import { DataTable, type DataColumn } from "@/components/ui/data-table"
import type { AssetSectionConfig, MetaAdsAssets } from "@/integrations/meta_ads/lib/assets"

export function AssetSection({
  exportFilename,
  result,
  section,
}: {
  exportFilename: string
  result: MetaAdsAssets
  section: AssetSectionConfig
}) {
  const items = result[section.kind]
  if (items.length === 0) return null
  const columns: DataColumn[] = [
    { key: "label", label: "Name", kind: "text" },
    ...(section.detail ? [{ key: "detail", label: section.detail, kind: "text" as const }] : []),
    { key: "id", label: "ID", kind: "id" },
  ]
  return (
    <section aria-label={section.title} className="grid min-w-0 gap-2">
      <h4 className="text-sm font-medium">{section.title}</h4>
      <DataTable
        columns={columns}
        rows={items}
        pageSize={10}
        exportFilename={exportFilename}
        truncationNote={
          result.truncated.includes(section.kind) ? "Meta has more than are shown here." : null
        }
      />
    </section>
  )
}
