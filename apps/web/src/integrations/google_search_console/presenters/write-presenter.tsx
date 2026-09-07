// apps/web/src/integrations/google_search_console/presenters/write-presenter.tsx

import type { ReactNode } from "react"
import { GoogleSearchConsoleLogo } from "@/integrations/google_search_console/components/logo"
import { GoogleSearchConsoleToolHeading } from "@/integrations/google_search_console/components/tool-heading"
import {
  createIntegrationWritePresenter,
  defineIntegrationWriteVariant,
  type IntegrationWriteProvider,
  type IntegrationWriteVariant,
} from "@/integrations/write-presenter"

type ApprovalSpec<Args> = {
  approveLabel: string
  label: string
  parseArgs: (value: unknown) => Args | null
  prompt: string
  renderSummary?: (args: Args) => ReactNode
  title: string
  validateArgs?: (value: unknown) => string | null
}

export type GoogleSearchConsoleWriteVariant<Args, Result> = Omit<
  IntegrationWriteVariant<Args, Result>,
  "approval" | "renderFailure" | "renderUnverifiedOutcome" | "progressLabel"
> & {
  approval: ApprovalSpec<Args>
  progressLabel: string
}

const provider: IntegrationWriteProvider = {
  contextLabel: "Site",
  externalLabel: "Site URL",
  fallbackDisplayName: "Selected Search Console site",
  providerKey: "google_search_console",
  renderHeading: (heading) => (
    <GoogleSearchConsoleToolHeading>{heading}</GoogleSearchConsoleToolHeading>
  ),
  renderIcon: () => <GoogleSearchConsoleLogo className="size-4" />,
}

export function defineGoogleSearchConsoleWriteVariant<Args, Result>(
  variant: GoogleSearchConsoleWriteVariant<Args, Result>
) {
  return defineIntegrationWriteVariant(provider, {
    ...variant,
    approval: {
      ...variant.approval,
      renderSummary: (value) => {
        const args = variant.approval.parseArgs(value)
        return args === null ? null : variant.approval.renderSummary?.(args)
      },
    },
    renderUnverifiedOutcome: variant.renderOutcome,
  })
}

export const createGoogleSearchConsoleWritePresenter = createIntegrationWritePresenter
