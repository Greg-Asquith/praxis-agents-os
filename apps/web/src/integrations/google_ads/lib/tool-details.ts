// apps/web/src/integrations/google_ads/lib/tool-details.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import { stringArg } from "@/integrations/tool-details"

export function googleAdsReportDetails(args: unknown): FanOutDetail[] {
  const query = stringArg(args, "query")
  return query ? [{ label: "GAQL query", summary: false, value: query }] : []
}
