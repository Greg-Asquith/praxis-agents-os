// apps/web/src/features/integrations/components/add-account-button.tsx

import { useState } from "react"
import { ExternalLinkIcon, KeyRoundIcon, PlusIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { ApiKeyConnectForm } from "@/features/integrations/components/api-key-connect-dialog"
import { OAuthConnectionForm } from "@/features/integrations/components/connect-oauth-button"
import { ServiceAccountConnectForm } from "@/features/integrations/components/service-account-connect-dialog"
import type { IntegrationProvider } from "@/features/integrations/types"
import { isOneOf } from "@/lib/guards"

type SupportedAuthMode = "api_key" | "oauth" | "service_account"

const SUPPORTED_AUTH_MODES = new Set<SupportedAuthMode>(["api_key", "oauth", "service_account"])

export function AddAccountButton({ provider }: { provider: IntegrationProvider }) {
  const modes = configuredModes(provider)
  const [open, setOpen] = useState(false)
  const [selectedMode, setSelectedMode] = useState<SupportedAuthMode | null>(null)

  function handleOpenChange(nextOpen: boolean) {
    setSelectedMode(nextOpen && modes.length === 1 ? (modes[0] ?? null) : null)
    setOpen(nextOpen)
  }

  function close() {
    handleOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger render={<Button />}>
        <PlusIcon data-icon="inline-start" />
        Add Connection
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        {selectedMode === null ? (
          <AuthModeChoice onSelect={setSelectedMode} provider={provider} />
        ) : null}
        {selectedMode === "oauth" ? (
          <OAuthConnectionForm onCancel={close} provider={provider} />
        ) : null}
        {selectedMode === "service_account" ? (
          <ServiceAccountConnectForm onCancel={close} onConnected={close} provider={provider} />
        ) : null}
        {selectedMode === "api_key" ? (
          <ApiKeyConnectForm onCancel={close} onConnected={close} provider={provider} />
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

function AuthModeChoice({
  onSelect,
  provider,
}: {
  onSelect: (mode: SupportedAuthMode) => void
  provider: IntegrationProvider
}) {
  const modes = configuredModes(provider)

  return (
    <>
      <DialogHeader>
        <DialogTitle>Add a {provider.display_name} Connection</DialogTitle>
        <DialogDescription>Choose how you want to connect this account.</DialogDescription>
      </DialogHeader>
      <div className="flex flex-col gap-3">
        {modes.includes("oauth") ? (
          <Button
            className="bg-muted/20 hover:bg-muted/50 h-auto justify-start px-4 py-3 text-left"
            onClick={() => {
              onSelect("oauth")
            }}
            type="button"
            variant="outline"
          >
            <ExternalLinkIcon className="mr-1 size-4 shrink-0" aria-hidden="true" />
            <span>
              <span className="block">Sign In With Google</span>
              <span className="mt-1 block text-xs font-normal opacity-80">
                Recommended - sign in and grant access in your browser
              </span>
            </span>
          </Button>
        ) : null}
        <details className="group rounded-lg border px-3 py-2">
          <summary className="focus-visible:ring-ring/50 cursor-pointer rounded-sm text-sm outline-none focus-visible:ring-[3px]">
            Advanced
          </summary>
          <div className="flex flex-col gap-2 pt-3">
            {modes.includes("service_account") ? (
              <Button
                className="justify-start"
                onClick={() => {
                  onSelect("service_account")
                }}
                type="button"
                variant="outline"
              >
                <KeyRoundIcon data-icon="inline-start" />
                Use a Service Account Key
              </Button>
            ) : null}
            {modes.includes("api_key") ? (
              <Button
                className="justify-start"
                onClick={() => {
                  onSelect("api_key")
                }}
                type="button"
                variant="outline"
              >
                <KeyRoundIcon data-icon="inline-start" />
                Use an API Key
              </Button>
            ) : null}
          </div>
        </details>
      </div>
    </>
  )
}

function configuredModes(provider: IntegrationProvider): SupportedAuthMode[] {
  return provider.auth_modes.filter(
    (mode): mode is SupportedAuthMode =>
      isOneOf(SUPPORTED_AUTH_MODES, mode) && provider.configured_auth_modes[mode] === true
  )
}
