// apps/web/src/features/integrations/components/credential-replacement-dialog.tsx

import { Dialog, DialogContent } from "@/components/ui/dialog"
import { ApiKeyConnectForm } from "@/features/integrations/components/api-key-connect-dialog"
import { ServiceAccountConnectForm } from "@/features/integrations/components/service-account-connect-dialog"
import type { IntegrationConnection, IntegrationProvider } from "@/features/integrations/types"

export function CredentialReplacementDialog({
  connection,
  onOpenChange,
  open,
  provider,
}: {
  connection: IntegrationConnection
  onOpenChange: (open: boolean) => void
  open: boolean
  provider: IntegrationProvider
}) {
  const authMode = connection.credential?.auth_mode

  function close() {
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        {authMode === "api_key" ? (
          <ApiKeyConnectForm
            onCancel={close}
            onConnected={close}
            provider={provider}
            replacementConnection={connection}
          />
        ) : null}
        {authMode === "service_account" ? (
          <ServiceAccountConnectForm
            onCancel={close}
            onConnected={close}
            provider={provider}
            replacementConnection={connection}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
