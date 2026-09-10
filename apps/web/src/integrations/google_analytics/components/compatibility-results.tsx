// apps/web/src/integrations/google_analytics/components/compatibility-results.tsx

import { AlertTriangleIcon, CheckCircle2Icon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import type { GoogleAnalyticsCompatibility } from "@/integrations/google_analytics/lib/compatibility-model"
import { metricLabel } from "@/integrations/google_analytics/lib/report-model"
import { pluralize } from "@/lib/format"

export function GoogleAnalyticsCompatibilityResults({
  result,
}: {
  result: GoogleAnalyticsCompatibility
}) {
  const incompatible = result.incompatibleFields.length
  return (
    <div className="grid gap-3">
      <p className="flex items-center gap-2 text-sm font-medium">
        {result.compatible ? (
          <CheckCircle2Icon aria-hidden="true" className="text-success size-4" />
        ) : (
          <AlertTriangleIcon aria-hidden="true" className="text-warning-foreground size-4" />
        )}
        {result.compatible
          ? "These can be reported together."
          : `${String(incompatible)} ${pluralize(incompatible, "field can't", "fields can't")} be combined.`}
      </p>
      <ul className="divide-border divide-y">
        {result.fields.map((field) => (
          <li className="flex items-center justify-between gap-3 py-2 text-sm" key={field.apiName}>
            <span>
              {metricLabel(field.apiName)}{" "}
              <span className="text-muted-foreground font-mono text-xs">{field.apiName}</span>
            </span>
            <Badge variant={field.compatible ? "success" : "warning"}>
              {field.compatible ? "Compatible" : "Incompatible"}
            </Badge>
          </li>
        ))}
      </ul>
    </div>
  )
}
