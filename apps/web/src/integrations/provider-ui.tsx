// apps/web/src/integrations/provider-ui.tsx

import type { ComponentType, ReactNode, SVGProps } from "react"

// One object per provider carries the identity every presenter needs.
export type IntegrationProviderUi = {
  /** Label for the connection on each fan-out card, such as "Account". */
  contextLabel: string
  /** Label for the connection's external identifier, or null when it is opaque. */
  externalLabel: string | null
  /** Card name used when a write settles without provider evidence. */
  fallbackDisplayName: string
  formatContextValue?: (value: string) => string
  Logo: ComponentType<SVGProps<SVGSVGElement>>
  /** Short product name used in headings and sentences, such as "Outlook". */
  name: string
  providerKey: string
}

export function IntegrationToolHeading({
  children,
  provider,
}: {
  children: ReactNode
  provider: IntegrationProviderUi
}) {
  return (
    <span className="inline-flex min-w-0 items-center gap-2 text-sm font-medium">
      <provider.Logo aria-hidden="true" className="size-4 shrink-0" />
      <span className="truncate">{children}</span>
    </span>
  )
}
