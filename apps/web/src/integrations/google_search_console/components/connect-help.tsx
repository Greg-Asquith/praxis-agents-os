// apps/web/src/integrations/google_search_console/components/connect-help.tsx

import { CloudCogIcon, ShieldCheckIcon } from "lucide-react"

import type { IntegrationProvider } from "@/features/integrations/types"
import { ConnectHelpCards } from "@/integrations/connect-help"

export function GoogleSearchConsoleConnectHelp({ provider }: { provider: IntegrationProvider }) {
  return (
    <ConnectHelpCards
      items={[
        {
          body: "Sign in with a Google account that can view the client properties agents should use. Owner permission is required for sitemap submissions and Indexing API actions.",
          icon: ShieldCheckIcon,
          title: "Choose an account with property access",
        },
        {
          body: `Enable the Google Search Console API in the Cloud project that owns the OAuth client used for ${provider.display_name}. If your operator has enabled Indexing API actions, enable the Indexing API in the same project.`,
          icon: CloudCogIcon,
          title: "Enable the Search Console APIs",
        },
      ]}
    />
  )
}
