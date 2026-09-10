// apps/web/src/integrations/microsoft-connect-help.tsx

import { Layers3Icon, ShieldCheckIcon, UnplugIcon } from "lucide-react"

import { ConnectHelpCards } from "@/integrations/connect-help"

export function MicrosoftConnectHelp({ provider }: { provider: { display_name: string } }) {
  return (
    <ConnectHelpCards
      items={[
        {
          body: `Before you connect ${provider.display_name}, your organisation's administrator sets up and approves the service. If sign-in mentions approval or assignment, ask them to finish that setup.`,
          icon: ShieldCheckIcon,
          title: "Your administrator approves access once",
        },
        {
          body: `Connecting ${provider.display_name} doesn't connect Outlook Mail, Outlook Calendar, or SharePoint automatically. Add only the services you want agents to use.`,
          icon: Layers3Icon,
          title: "Connect each service separately",
        },
        {
          body: (
            <>
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
            </>
          ),
          icon: UnplugIcon,
          title: "Remove Microsoft access separately",
        },
      ]}
    />
  )
}
