// apps/web/src/integrations/bigquery/components/connect-help.tsx

import { LightbulbIcon, ShieldCheckIcon } from "lucide-react"

import type { IntegrationProvider } from "@/features/integrations/types"
import { ConnectHelpCards } from "@/integrations/connect-help"

export function BigQueryConnectHelp({ provider }: { provider: IntegrationProvider }) {
  return (
    <ConnectHelpCards
      items={[
        {
          body: "Grant BigQuery Job User on the service account's project, BigQuery Metadata Viewer on each project the system should discover, and BigQuery Data Viewer only on datasets agents should read.",
          icon: ShieldCheckIcon,
          title: "Give agents read-only access",
        },
        {
          body: `Add clear descriptions to your BigQuery tables and columns. ${provider.display_name} makes those descriptions available whenever an agent plans a query.`,
          icon: LightbulbIcon,
          title: "Help agents write accurate queries",
        },
      ]}
    />
  )
}
