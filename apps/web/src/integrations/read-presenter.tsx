// apps/web/src/integrations/read-presenter.tsx

import type { ReactNode } from "react"

import { Badge } from "@/components/ui/badge"
import { parseFanOutData, type FanOutEntry } from "@/components/tool-ui/fan-out"
import { FanOutShell, FanOutSkeleton, type FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import { ToolResultCard, type ToolResultDetail } from "@/components/tool-ui/result-card"
import type { ToolRowPresenter } from "@/integrations/contract"
import { IntegrationToolHeading, type IntegrationProviderUi } from "@/integrations/provider-ui"

export type IntegrationReadVariant<Result> = {
  ariaLabel: string
  details?: (args: unknown) => FanOutDetail[]
  emptyLabel: string
  heading: string
  parseResult: (value: unknown) => Result | null
  progressLabel: string
  render: (result: Result, entry: FanOutEntry) => ReactNode
  tool: string
}

export type IntegrationResultVariant<Result> = {
  ariaLabel: string
  details?: (result: Result, args: unknown) => ToolResultDetail[]
  heading: string
  parseResult: (value: unknown) => Result | null
  progressLabel: string
  render: (result: Result, args: unknown) => ReactNode
  tool: string
  trailing?: (result: Result) => ReactNode
}

// Reads render nothing for failed or malformed activities so the default row shows the error.
export function defineIntegrationReadPresenter<Result>(
  provider: IntegrationProviderUi,
  variant: IntegrationReadVariant<Result>
): ToolRowPresenter {
  const heading = (
    <IntegrationToolHeading provider={provider}>{variant.heading}</IntegrationToolHeading>
  )
  return {
    key: variant.tool,
    matches: (activity) => activity.name === variant.tool,
    render: ({ activity, defaultOpen }) => {
      if (activity.status === "running") {
        return <FanOutSkeleton heading={heading} label={variant.progressLabel} />
      }
      const fanOut = parseFanOutData(activity.result, variant.parseResult)
      if (!fanOut) {
        return null
      }
      return (
        <div aria-label={variant.ariaLabel} className="w-full min-w-0">
          <FanOutShell
            contextLabel={provider.contextLabel}
            defaultOpen={defaultOpen}
            {...(variant.details ? { details: variant.details(activity.args) } : {})}
            entries={fanOut.entries}
            emptyLabel={variant.emptyLabel}
            externalLabel={provider.externalLabel}
            {...(provider.formatContextValue
              ? { formatContextValue: provider.formatContextValue }
              : {})}
            heading={heading}
          >
            {(entry, index) => {
              const result = fanOut.data[index]
              return result === null || result === undefined ? null : variant.render(result, entry)
            }}
          </FanOutShell>
        </div>
      )
    },
  }
}

// For tools whose result is one document rather than a per-connection fan-out.
export function defineIntegrationResultPresenter<Result>(
  provider: IntegrationProviderUi,
  variant: IntegrationResultVariant<Result>
): ToolRowPresenter {
  const heading = (
    <IntegrationToolHeading provider={provider}>{variant.heading}</IntegrationToolHeading>
  )
  return {
    key: variant.tool,
    matches: (activity) => activity.name === variant.tool,
    render: ({ activity, defaultOpen }) => {
      if (activity.status === "running") {
        return <FanOutSkeleton heading={heading} label={variant.progressLabel} />
      }
      const result = variant.parseResult(activity.result)
      if (result === null) {
        return null
      }
      return (
        <ToolResultCard
          ariaLabel={variant.ariaLabel}
          defaultOpen={defaultOpen}
          {...(variant.details ? { details: variant.details(result, activity.args) } : {})}
          heading={heading}
          trailing={variant.trailing?.(result) ?? <Badge variant="success">Done</Badge>}
        >
          {variant.render(result, activity.args)}
        </ToolResultCard>
      )
    },
  }
}
