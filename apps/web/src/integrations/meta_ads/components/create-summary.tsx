// apps/web/src/integrations/meta_ads/components/create-summary.tsx

import { MetaAdsApprovalSection } from "@/integrations/meta_ads/components/approval-section"
import { MetaAdsOutcomeTable, OutcomeLink } from "@/integrations/meta_ads/components/outcome-table"
import { adsManagerObjectUrl } from "@/integrations/meta_ads/lib/ads-manager-link"
import {
  PAUSED_NOTE,
  type CreatedObjectResult,
  type SummaryLine,
} from "@/integrations/meta_ads/lib/create-summary"

/** A new campaign or ad set in labelled sentences, under the created-paused note. */
export function CreateSummary({ ariaLabel, lines }: { ariaLabel: string; lines: SummaryLine[] }) {
  return (
    <MetaAdsApprovalSection ariaLabel={ariaLabel} warning={PAUSED_NOTE}>
      <dl className="grid min-w-0 gap-2 text-sm sm:grid-cols-[8rem_minmax(0,1fr)]">
        {lines.map((line) => (
          <div className="contents" key={line.label}>
            <dt className="text-muted-foreground font-medium">{line.label}</dt>
            <dd className="grid min-w-0 gap-0.5 wrap-anywhere">
              {line.sentences.map((sentence) => (
                <p key={sentence}>{sentence}</p>
              ))}
            </dd>
          </div>
        ))}
      </dl>
    </MetaAdsApprovalSection>
  )
}

const OBJECTS = {
  campaign: {
    title: "Campaign",
    noun: "campaign",
    next: "The campaign is paused. Ask the agent to create ad sets and ads in it, then turn it on.",
  },
  adset: {
    title: "Ad Set",
    noun: "ad set",
    next: "The ad set is paused. Ask the agent to create ads in it, then turn it on.",
  },
} as const

export function CreatedObjectOutcome({
  result,
  type,
}: {
  result: CreatedObjectResult
  type: keyof typeof OBJECTS
}) {
  const { title, noun, next } = OBJECTS[type]
  const manager = result.id ? adsManagerObjectUrl(type, result.accountId, result.id) : null
  return (
    <div className="grid gap-3">
      <MetaAdsOutcomeTable
        columns={[
          { key: "name", kind: "text", label: title },
          { key: "links", kind: "text", label: "Links" },
        ]}
        exportFilename={`meta-ads-created-${noun.replace(" ", "-")}.csv`}
        renderCell={(column) =>
          column.key === "links" && manager ? (
            <OutcomeLink href={manager}>Open in Ads Manager</OutcomeLink>
          ) : null
        }
        rows={[
          {
            name: result.name,
            links: "",
            outcome: result.outcome,
            details: [
              result.message,
              result.recovered
                ? `Meta's reply was lost, so the ${noun} was found by its name.`
                : null,
            ]
              .filter(Boolean)
              .join(" "),
            errorCode: result.errorCode,
          },
        ]}
      />
      {result.outcome === "created" ? <p className="text-sm">{next}</p> : null}
    </div>
  )
}
