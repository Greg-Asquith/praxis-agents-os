// apps/web/src/integrations/microsoft-connect-help.tsx

import { Layers3Icon, ShieldCheckIcon, UnplugIcon } from "lucide-react"

type MicrosoftConnectHelpProps = {
  provider: { display_name: string }
}

export function MicrosoftConnectHelp({ provider }: MicrosoftConnectHelpProps) {
  return (
    <div className="border-border bg-muted/20 grid gap-4 rounded-xl border p-4 lg:grid-cols-3">
      <div className="flex gap-3">
        <ShieldCheckIcon
          aria-hidden="true"
          className="text-muted-foreground mt-0.5 size-4 shrink-0"
        />
        <div className="grid gap-1">
          <h2 className="text-sm font-medium">Your administrator approves access once</h2>
          <p className="text-muted-foreground text-sm">
            Before you connect {provider.display_name}, your organization&apos;s administrator sets
            up and approves the service. If sign-in mentions approval or assignment, ask them to
            finish that setup.
          </p>
        </div>
      </div>
      <div className="flex gap-3">
        <Layers3Icon aria-hidden="true" className="text-muted-foreground mt-0.5 size-4 shrink-0" />
        <div className="grid gap-1">
          <h2 className="text-sm font-medium">Connect each service separately</h2>
          <p className="text-muted-foreground text-sm">
            Connecting {provider.display_name} doesn&apos;t connect Outlook Mail, Outlook Calendar,
            or SharePoint automatically. Add only the services you want agents to use.
          </p>
        </div>
      </div>
      <div className="flex gap-3">
        <UnplugIcon aria-hidden="true" className="text-muted-foreground mt-0.5 size-4 shrink-0" />
        <div className="grid gap-1">
          <h2 className="text-sm font-medium">Remove Microsoft access separately</h2>
          <p className="text-muted-foreground text-sm">
            After you remove this connection from Praxis, you can also remove the application from
            your{" "}
            <a
              className="text-foreground underline underline-offset-4"
              href="https://myapps.microsoft.com"
              rel="noreferrer"
              target="_blank"
            >
              Microsoft Apps portal
            </a>
            .
          </p>
        </div>
      </div>
    </div>
  )
}
