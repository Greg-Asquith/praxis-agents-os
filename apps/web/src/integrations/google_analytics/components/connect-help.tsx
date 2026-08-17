// apps/web/src/integrations/google_analytics/components/connect-help.tsx

import { CloudCogIcon, ShieldCheckIcon } from "lucide-react"

import type { IntegrationProvider } from "@/features/integrations/types"

export function GoogleAnalyticsConnectHelp({ provider }: { provider: IntegrationProvider }) {
  return (
    <div className="border-border bg-muted/20 grid gap-4 rounded-xl border p-4 sm:grid-cols-2">
      <div className="flex gap-3">
        <ShieldCheckIcon
          aria-hidden="true"
          className="text-muted-foreground mt-0.5 size-4 shrink-0"
        />
        <div className="grid gap-1">
          <h2 className="text-sm font-medium">Choose an account with property access</h2>
          <p className="text-muted-foreground text-sm">
            Sign in with a Google account that can view the client properties agents should read.
            For a service account, add its email as a Viewer on each Analytics account or property.
          </p>
        </div>
      </div>
      <div className="flex gap-3">
        <CloudCogIcon aria-hidden="true" className="text-muted-foreground mt-0.5 size-4 shrink-0" />
        <div className="grid gap-1">
          <h2 className="text-sm font-medium">Enable both Analytics APIs</h2>
          <p className="text-muted-foreground text-sm">
            Enable the Google Analytics Data API and Admin API in the Cloud project that owns the
            OAuth client or service account used for {provider.display_name}.
          </p>
        </div>
      </div>
    </div>
  )
}
