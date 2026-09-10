// apps/web/src/integrations/google_analytics/components/connect-help.tsx

import { CloudCogIcon, ShieldCheckIcon } from "lucide-react"

import type { IntegrationProvider } from "@/features/integrations/types"
import { ConnectHelpCards } from "@/integrations/connect-help"

export function GoogleAnalyticsConnectHelp({ provider }: { provider: IntegrationProvider }) {
  return (
    <ConnectHelpCards
      items={[
        {
          body: "Sign in with a Google account that can view the client properties agents should read. For a service account, add its email as a Viewer on each Analytics account or property.",
          icon: ShieldCheckIcon,
          title: "Choose an account with property access",
        },
        {
          body: `Enable the Google Analytics Data API and Admin API in the Cloud project that owns the OAuth client or service account used for ${provider.display_name}.`,
          icon: CloudCogIcon,
          title: "Enable both Analytics APIs",
        },
      ]}
    />
  )
}
