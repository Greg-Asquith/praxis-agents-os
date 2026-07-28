// apps/web/src/integrations/bigquery/components/conenct-help.tsx

import { LightbulbIcon, ShieldCheckIcon } from "lucide-react"

import type { IntegrationProvider } from "@/features/integrations/types"

export function BigQueryConnectHelp({ provider }: { provider: IntegrationProvider }) {
  return (
    <div className="border-border/70 bg-muted/20 grid gap-4 rounded-xl border p-4 sm:grid-cols-2">
      <div className="flex gap-3">
        <ShieldCheckIcon
          aria-hidden="true"
          className="text-muted-foreground mt-0.5 size-4 shrink-0"
        />
        <div className="grid gap-1">
          <h2 className="text-sm font-medium">Give agents read-only access</h2>
          <p className="text-muted-foreground text-sm">
            Grant the service account BigQuery Job User on its project and BigQuery Data Viewer only
            on the projects or datasets agents should read.
          </p>
        </div>
      </div>
      <div className="flex gap-3">
        <LightbulbIcon
          aria-hidden="true"
          className="text-muted-foreground mt-0.5 size-4 shrink-0"
        />
        <div className="grid gap-1">
          <h2 className="text-sm font-medium">Help agents write accurate queries</h2>
          <p className="text-muted-foreground text-sm">
            Add clear descriptions to your BigQuery tables and columns. {provider.display_name}{" "}
            makes those descriptions available whenever an agent plans a query.
          </p>
        </div>
      </div>
    </div>
  )
}
