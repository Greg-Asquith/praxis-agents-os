// apps/web/src/features/integrations/components/provider-mark.tsx

import { PlugZapIcon } from "lucide-react"

import { useIntegrationUiModule } from "@/integrations/registry"

export function ProviderMark({
  className,
  providerKey,
}: {
  className?: string
  providerKey: string
}) {
  const module = useIntegrationUiModule(providerKey)
  const Icon = module?.icons?.[providerKey] ?? PlugZapIcon
  return <Icon className={className} aria-hidden="true" />
}
