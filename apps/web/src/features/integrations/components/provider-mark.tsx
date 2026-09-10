// apps/web/src/features/integrations/components/provider-mark.tsx

import { PlugZapIcon } from "lucide-react"

import { useIntegrationUiModule } from "@/integrations/registry"
import { cn } from "@/lib/utils"

export function ProviderMark({
  className,
  providerKey,
}: {
  className?: string
  providerKey: string
}) {
  const module = useIntegrationUiModule(providerKey)
  const Icon = module?.Logo ?? PlugZapIcon
  return <Icon className={cn("size-4", className)} aria-hidden="true" />
}
