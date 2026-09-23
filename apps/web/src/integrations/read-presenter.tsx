// apps/web/src/integrations/read-presenter.tsx

import type { ReactNode } from "react"

import { Badge } from "@/components/ui/badge"
import { parseFanOutData, type FanOutEntry } from "@/components/tool-ui/fan-out"
import { FanOutShell, FanOutSkeleton, type FanOutDetail } from "@/components/tool-ui/fan-out-shell"
import { ToolResultCard, type ToolResultDetail } from "@/components/tool-ui/result-card"
import { parseResultPreview } from "@/components/tool-ui/result-preview"
import { RetainedResult } from "@/components/tool-ui/retained-result"
import { ResultPreviewNotice } from "@/components/tool-ui/result-preview-notice"
import type { ToolRowPresenter } from "@/integrations/contract"
import { IntegrationToolHeading, type IntegrationProviderUi } from "@/integrations/provider-ui"

export type IntegrationReadVariant<Result> = {
  ariaLabel: string
  details?: (args: unknown) => FanOutDetail[]
  emptyLabel: string
  heading: string
  parseResult: (value: unknown) => Result | null
  progressLabel: string
  render: (result: Result, entry: FanOutEntry, args: unknown, preview: boolean) => ReactNode
  renderFailed?: (entry: FanOutEntry) => ReactNode
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
      const envelope = parseResultPreview(activity.result)
      const preview = envelope ?? parseResultPreview(activity.resultPreview)
      const data = envelope ? envelope.data : activity.result
      const fanOut = parseFanOutData(data, variant.parseResult)
      if (!fanOut) {
        return null
      }
      const renderResult = (visibleData: unknown, incomplete: boolean, control?: ReactNode) => {
        const visible =
          visibleData === data ? fanOut : parseFanOutData(visibleData, variant.parseResult)
        if (!visible) return null
        return (
          <div aria-label={variant.ariaLabel} className="w-full min-w-0">
            <FanOutShell
              contextLabel={provider.contextLabel}
              defaultOpen={defaultOpen}
              {...(variant.details ? { details: variant.details(activity.args) } : {})}
              entries={visible.entries}
              emptyLabel={variant.emptyLabel}
              externalLabel={provider.externalLabel}
              {...(provider.formatContextValue
                ? { formatContextValue: provider.formatContextValue }
                : {})}
              heading={heading}
              {...(variant.renderFailed ? { renderFailed: variant.renderFailed } : {})}
            >
              {(entry, index) => {
                const result = visible.data[index]
                if (result === null || result === undefined) return null
                return (
                  <div className="grid min-w-0 gap-3">
                    {control}
                    {preview ? (
                      <ResultPreviewNotice data={visibleData} index={index} preview={preview} />
                    ) : null}
                    {variant.render(result, entry, activity.args, incomplete)}
                  </div>
                )
              }}
            </FanOutShell>
          </div>
        )
      }
      return envelope ? (
        <RetainedResult
          key={envelope.fileId}
          preview={envelope}
          validate={(value) => parseFanOutData(value, variant.parseResult) !== null}
        >
          {renderResult}
        </RetainedResult>
      ) : (
        renderResult(data, false)
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
      const envelope = parseResultPreview(activity.result)
      const preview = envelope ?? parseResultPreview(activity.resultPreview)
      const data = envelope?.data ?? activity.result
      const result = variant.parseResult(data)
      if (result === null) return null
      const renderResult = (visibleData: unknown, _incomplete: boolean, control?: ReactNode) => {
        const visible = visibleData === data ? result : variant.parseResult(visibleData)
        if (visible === null) return null
        return (
          <ToolResultCard
            ariaLabel={variant.ariaLabel}
            defaultOpen={defaultOpen}
            {...(variant.details ? { details: variant.details(visible, activity.args) } : {})}
            heading={heading}
            trailing={variant.trailing?.(visible) ?? <Badge variant="success">Done</Badge>}
          >
            {control}
            {preview ? <ResultPreviewNotice data={visibleData} preview={preview} /> : null}
            {variant.render(visible, activity.args)}
          </ToolResultCard>
        )
      }
      return envelope ? (
        <RetainedResult
          key={envelope.fileId}
          preview={envelope}
          validate={(value) => variant.parseResult(value) !== null}
        >
          {renderResult}
        </RetainedResult>
      ) : (
        renderResult(data, false)
      )
    },
  }
}
