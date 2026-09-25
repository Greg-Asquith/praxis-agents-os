// apps/web/src/integrations/meta_ads/lib/tool-details.ts

import type { FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import { compactDetails, listDetail, stringArg } from "@/integrations/tool-details"
import { titleCaseToken } from "@/lib/format"

export function insightsDetails(args: unknown): FanOutDetail[] {
  const since = stringArg(args, "since")
  const until = stringArg(args, "until")
  return compactDetails([
    since && until ? { label: "Range", value: `${since} → ${until}` } : null,
    { label: "Level", value: titleCaseToken(stringArg(args, "level") ?? "campaign", "Campaign") },
    listDetail(args, "breakdowns", "Breakdowns", (value) => titleCaseToken(value, value)),
    listDetail(args, "action_breakdowns", "Action breakdowns", (value) =>
      titleCaseToken(value, value)
    ),
    listDetail(args, "attribution_windows", "Attribution", (value) =>
      titleCaseToken(value, value)
    ) ?? {
      label: "Attribution",
      value: "Ad set settings",
    },
  ])
}
