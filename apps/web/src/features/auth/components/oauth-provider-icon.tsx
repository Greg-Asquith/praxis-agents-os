// apps/web/src/features/auth/components/oauth-provider-icon.tsx

import { LogInIcon } from "lucide-react"
import { GoogleIcon, GitHubIcon, MicrosoftIcon } from "@/components/ui/icons"
import { normalize } from "@/lib/format"

type ProviderIconProps = {
  provider: string
}

const providerIcons = {
  github: GitHubIcon,
  google: GoogleIcon,
  microsoft: MicrosoftIcon,
} as const

export function OAuthProviderIcon({ provider }: ProviderIconProps) {
  const normalizedProvider = normalize(provider) ?? ""
  if (!isProviderIconKey(normalizedProvider)) {
    return <LogInIcon data-icon="inline-start" />
  }

  const Icon = providerIcons[normalizedProvider]
  return <Icon aria-hidden="true" data-icon="inline-start" />
}

function isProviderIconKey(provider: string): provider is keyof typeof providerIcons {
  return provider in providerIcons
}
