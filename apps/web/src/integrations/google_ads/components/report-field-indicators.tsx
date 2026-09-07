// apps/web/src/integrations/google_ads/components/report-field-indicators.tsx

import { Badge } from "@/components/ui/badge"

export function ReportFieldsDone() {
  return <Badge variant="success">Done</Badge>
}

export function ReportFieldFlag({ label, value }: { label: string; value: boolean }) {
  return (
    <div className="flex items-center gap-1.5">
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd>
        <Badge variant={value ? "success" : "outline"}>{value ? "Yes" : "No"}</Badge>
      </dd>
    </div>
  )
}
