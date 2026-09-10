// apps/web/src/integrations/notion/components/connect-help.tsx

import { FileCheckIcon, UserRoundCheckIcon, UsersRoundIcon } from "lucide-react"

import type { IntegrationProvider } from "@/features/integrations/types"
import { ConnectHelpCards } from "@/integrations/connect-help"

export function NotionConnectHelp({ provider }: { provider: IntegrationProvider }) {
  return (
    <ConnectHelpCards
      items={[
        {
          body: `The ${provider.display_name} authorisation picker decides which pages this connection can read. Select only the pages you want available to the agent.`,
          icon: FileCheckIcon,
          title: "Choose pages during authorisation",
        },
        {
          body: "Other users authorise separately with their own Notion account, so each connection follows that person's Notion access.",
          icon: UsersRoundIcon,
          title: "Connect your own account",
        },
        {
          body: "The person who connects must be an editor in this workspace.",
          icon: UserRoundCheckIcon,
          title: "Use an editor account",
        },
      ]}
    />
  )
}
