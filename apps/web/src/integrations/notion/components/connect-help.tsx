// apps/web/src/integrations/notion/components/connect-help.tsx

import { FileCheckIcon, UserRoundCheckIcon, UsersRoundIcon } from "lucide-react"

import type { IntegrationProvider } from "@/features/integrations/types"

export function NotionConnectHelp({ provider }: { provider: IntegrationProvider }) {
  return (
    <div className="border-border bg-muted/20 grid gap-4 rounded-xl border p-4 lg:grid-cols-3">
      <div className="flex gap-3">
        <FileCheckIcon
          aria-hidden="true"
          className="text-muted-foreground mt-0.5 size-4 shrink-0"
        />
        <div className="grid gap-1">
          <h2 className="text-sm font-medium">Choose pages during authorization</h2>
          <p className="text-muted-foreground text-sm">
            The {provider.display_name} authorization picker decides which pages this connection can
            read. Select only the pages you want available the the agent.
          </p>
        </div>
      </div>
      <div className="flex gap-3">
        <UsersRoundIcon
          aria-hidden="true"
          className="text-muted-foreground mt-0.5 size-4 shrink-0"
        />
        <div className="grid gap-1">
          <h2 className="text-sm font-medium">Connect your own account</h2>
          <p className="text-muted-foreground text-sm">
            Other users authorise separately with their own Notion account, so each
            connection follows that person's Notion access.
          </p>
        </div>
      </div>
      <div className="flex gap-3">
        <UserRoundCheckIcon
          aria-hidden="true"
          className="text-muted-foreground mt-0.5 size-4 shrink-0"
        />
        <div className="grid gap-1">
          <h2 className="text-sm font-medium">Use an editor account</h2>
          <p className="text-muted-foreground text-sm">
            The person who connects must be an editor in this workspace.
          </p>
        </div>
      </div>
    </div>
  )
}
