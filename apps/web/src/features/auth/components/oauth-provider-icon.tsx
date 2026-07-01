// apps/web/src/features/auth/components/oauth-provider-icon.tsx

import type { SVGProps } from "react"
import { LogInIcon } from "lucide-react"

type ProviderIconProps = {
  provider: string
}

type SvgProps = SVGProps<SVGSVGElement>

const providerIcons = {
  github: GitHubIcon,
  google: GoogleIcon,
  microsoft: MicrosoftIcon,
} as const

export function OAuthProviderIcon({ provider }: ProviderIconProps) {
  const normalizedProvider = provider.trim().toLowerCase()
  if (!isProviderIconKey(normalizedProvider)) {
    return <LogInIcon data-icon="inline-start" />
  }

  const Icon = providerIcons[normalizedProvider]
  return <Icon aria-hidden="true" data-icon="inline-start" />
}

function isProviderIconKey(provider: string): provider is keyof typeof providerIcons {
  return provider in providerIcons
}

function GoogleIcon(props: SvgProps) {
  return (
    <svg viewBox="0 0 24 24" {...props}>
      <path
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
        fill="#4285f4"
      />
      <path
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
        fill="#34a853"
      />
      <path
        d="M5.84 14.1c-.22-.66-.35-1.36-.35-2.1s.13-1.44.35-2.1V7.06H2.18C1.43 8.55 1 10.23 1 12s.43 3.45 1.18 4.94l3.66-2.84z"
        fill="#fbbc05"
      />
      <path
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06L5.84 9.9C6.71 7.31 9.14 5.38 12 5.38z"
        fill="#ea4335"
      />
    </svg>
  )
}

function GitHubIcon(props: SvgProps) {
  return (
    <svg viewBox="0 0 24 24" {...props}>
      <path
        d="M12 .5C5.65.5.5 5.65.5 12c0 5.09 3.29 9.39 7.86 10.91.58.11.79-.25.79-.56 0-.28-.01-1.02-.02-2-3.2.7-3.88-1.54-3.88-1.54-.52-1.33-1.28-1.68-1.28-1.68-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.76 2.7 1.25 3.36.96.1-.75.4-1.25.73-1.54-2.55-.29-5.23-1.28-5.23-5.68 0-1.25.45-2.28 1.18-3.08-.12-.29-.51-1.46.11-3.04 0 0 .97-.31 3.17 1.18A11.04 11.04 0 0 1 12 5.53c.98 0 1.96.13 2.88.39 2.2-1.49 3.16-1.18 3.16-1.18.63 1.58.23 2.75.12 3.04.74.8 1.18 1.83 1.18 3.08 0 4.41-2.69 5.38-5.25 5.67.42.36.78 1.07.78 2.15 0 1.55-.01 2.8-.01 3.18 0 .31.21.68.8.56A11.52 11.52 0 0 0 23.5 12C23.5 5.65 18.35.5 12 .5z"
        fill="currentColor"
      />
    </svg>
  )
}

function MicrosoftIcon(props: SvgProps) {
  return (
    <svg viewBox="0 0 24 24" {...props}>
      <path d="M2 2h9.5v9.5H2z" fill="#f25022" />
      <path d="M12.5 2H22v9.5h-9.5z" fill="#7fba00" />
      <path d="M2 12.5h9.5V22H2z" fill="#00a4ef" />
      <path d="M12.5 12.5H22V22h-9.5z" fill="#ffb900" />
    </svg>
  )
}
