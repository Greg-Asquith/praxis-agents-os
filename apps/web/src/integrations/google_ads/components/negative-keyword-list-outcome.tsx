// apps/web/src/integration/google_ads/components/negative-keyword-list-outcome.tsx

import type { ReactNode } from "react"
import { AlertCircleIcon, CircleCheckIcon, CircleMinusIcon } from "lucide-react"

import { KpiStrip } from "@/components/tool-ui/kpi"
import { Badge } from "@/components/ui/badge"
import { titleCaseToken } from "@/lib/format"

export type NegativeKeywordListError = {
  errorCode: string
  message: string
  name: string
}

export type NegativeKeywordListResult = {
  createdNames: string[]
  errors: NegativeKeywordListError[]
  skippedNames: string[]
}

export function NegativeKeywordListOutcome({ result }: { result: NegativeKeywordListResult }) {
  return (
    <div className="grid min-w-0 gap-3">
      <KpiStrip
        items={[
          { label: "Created", tone: "success", value: result.createdNames.length },
          { label: "Already existed", tone: "neutral", value: result.skippedNames.length },
          {
            label: "Failed",
            tone: result.errors.length > 0 ? "danger" : "neutral",
            value: result.errors.length,
          },
        ]}
      />
      <div className="grid gap-1" role="list">
        {result.createdNames.map((name) => (
          <OutcomeRow
            icon={<CircleCheckIcon className="text-success size-4" />}
            key={`created:${name}`}
            name={name}
          >
            <Badge variant="success">Created</Badge>
          </OutcomeRow>
        ))}
        {result.skippedNames.map((name) => (
          <OutcomeRow
            icon={<CircleMinusIcon className="text-muted-foreground size-4" />}
            key={`skipped:${name}`}
            name={name}
          >
            <Badge variant="secondary">Already existed</Badge>
          </OutcomeRow>
        ))}
        {result.errors.map((error, index) => (
          <div
            className="bg-destructive/5 grid min-w-0 gap-1 rounded-md px-2 py-2"
            key={`failed:${error.name}:${String(index)}`}
            role="listitem"
          >
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <AlertCircleIcon className="text-destructive size-4" />
              <span className="min-w-0 flex-1 text-sm">
                {error.name || "Negative keyword list"}
              </span>
              <Badge variant="destructive">Failed</Badge>
            </div>
            <p className="text-destructive pl-6 text-xs">{error.message}</p>
            {error.errorCode ? (
              <p className="text-muted-foreground pl-6 text-xs">
                {titleCaseToken(error.errorCode, error.errorCode)}
              </p>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  )
}

function OutcomeRow({
  children,
  icon,
  name,
}: {
  children: ReactNode
  icon: ReactNode
  name: string
}) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2 rounded-md px-2 py-2" role="listitem">
      {icon}
      <span className="min-w-0 flex-1 text-sm">{name}</span>
      {children}
    </div>
  )
}
