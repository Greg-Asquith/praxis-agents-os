// apps/web/src/integrations/google_search_console/lib/sitemaps-model.ts

import { isUntrustedNode } from "@/components/tool-ui/untrusted-node"
import type { DataRow } from "@/components/ui/data-table-model"
import { isRecord } from "@/lib/guards"

export function parseSitemapsData(value: unknown): DataRow[] | null {
  if (!isRecord(value) || !Array.isArray(value["sitemaps"])) {
    return null
  }
  const rows: DataRow[] = []
  for (const item of value["sitemaps"]) {
    const row = parseSitemap(item)
    if (!row) return null
    rows.push(row)
  }
  return rows
}

function parseSitemap(value: unknown): DataRow | null {
  if (
    !isRecord(value) ||
    !isUntrustedNode(value["path"]) ||
    typeof value["type"] !== "string" ||
    (value["last_submitted"] !== null && typeof value["last_submitted"] !== "string") ||
    typeof value["is_pending"] !== "boolean" ||
    typeof value["is_sitemaps_index"] !== "boolean" ||
    typeof value["warnings"] !== "number" ||
    typeof value["errors"] !== "number" ||
    typeof value["submitted_url_count"] !== "number"
  ) {
    return null
  }
  return {
    errors: value["errors"],
    last_submitted: value["last_submitted"],
    path: value["path"],
    pending: value["is_pending"] ? "Pending" : "Processed",
    submitted_url_count: value["submitted_url_count"],
    type: value["is_sitemaps_index"] ? "Sitemap index" : value["type"],
    warnings: value["warnings"],
  }
}
