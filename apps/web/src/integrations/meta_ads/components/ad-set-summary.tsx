// apps/web/src/integrations/meta_ads/components/ad-set-summary.tsx

import type { EditedValue } from "@/components/tool-ui/edited-values"
import { MetaAdsApprovalSection } from "@/integrations/meta_ads/components/approval-section"
import { OutcomeLink } from "@/integrations/meta_ads/components/create-ads"
import { LabelledInput } from "@/integrations/meta_ads/components/editor-fields"
import { MetaAdsOutcomeTable } from "@/integrations/meta_ads/components/outcome-table"
import { adsManagerObjectUrl } from "@/integrations/meta_ads/lib/ads-manager-link"
import {
  adSetSummary,
  PAUSED_NOTE,
  type CreateAdSetArgs,
  type CreateAdSetResult,
} from "@/integrations/meta_ads/lib/create-ad-set"

export function CreateAdSetApproval({
  args,
  disabled,
  onFieldEdit,
}: {
  args: CreateAdSetArgs
  disabled: boolean
  onFieldEdit: (key: string, value: EditedValue) => void
}) {
  const ages = (key: "age_min" | "age_max", value: string) => {
    const number = Number.parseInt(value, 10)
    const { [key]: _previous, ...rest } = args.targeting
    onFieldEdit("targeting", Number.isFinite(number) ? { ...rest, [key]: number } : rest)
  }
  const ageMin = args.targeting["age_min"]
  const ageMax = args.targeting["age_max"]
  return (
    <div className="grid min-w-0 gap-3">
      <MetaAdsApprovalSection ariaLabel="Ad Set Summary" warning={PAUSED_NOTE}>
        <dl className="grid min-w-0 gap-2 text-sm sm:grid-cols-[8rem_minmax(0,1fr)]">
          {adSetSummary(args).map((line) => (
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
      <p className="text-muted-foreground text-xs">
        To change the goal, places, or interests, decline and ask the agent.
      </p>
      <div className="grid min-w-0 gap-3 sm:grid-cols-3">
        {args.budget ? (
          <LabelledInput
            disabled={disabled}
            id="meta-ads-ad-set-budget"
            label={args.budget.kind === "daily" ? "Daily Budget" : "Lifetime Budget"}
            onChange={(amount) => {
              onFieldEdit("budget", { kind: args.budget?.kind ?? "daily", amount: amount.trim() })
            }}
            value={args.budget.amount}
          />
        ) : null}
        <LabelledInput
          disabled={disabled}
          id="meta-ads-ad-set-age-min"
          label="Minimum Age"
          onChange={(value) => {
            ages("age_min", value)
          }}
          value={typeof ageMin === "number" ? String(ageMin) : "18"}
        />
        <LabelledInput
          disabled={disabled}
          id="meta-ads-ad-set-age-max"
          label="Maximum Age"
          onChange={(value) => {
            ages("age_max", value)
          }}
          placeholder="65+"
          value={typeof ageMax === "number" ? String(ageMax) : ""}
        />
      </div>
    </div>
  )
}

export function CreateAdSetOutcome({ result }: { result: CreateAdSetResult }) {
  const { adSet } = result
  const manager = adSet.adSetId
    ? adsManagerObjectUrl("adset", result.accountId, adSet.adSetId)
    : null
  return (
    <div className="grid gap-3">
      <MetaAdsOutcomeTable
        columns={[
          { key: "name", kind: "text", label: "Ad Set" },
          { key: "links", kind: "text", label: "Links" },
        ]}
        exportFilename="meta-ads-created-ad-set.csv"
        renderCell={(column) =>
          column.key === "links" && manager ? (
            <OutcomeLink href={manager}>Open in Ads Manager</OutcomeLink>
          ) : null
        }
        rows={[
          {
            name: adSet.name,
            links: "",
            outcome: adSet.outcome,
            details: [
              adSet.message,
              adSet.recovered
                ? "Meta's reply was lost, so the ad set was found by its name."
                : null,
            ]
              .filter(Boolean)
              .join(" "),
            errorCode: adSet.errorCode,
          },
        ]}
      />
      {adSet.outcome === "created" ? (
        <p className="text-sm">
          The ad set is paused. Ask the agent to create ads in it, then turn it on.
        </p>
      ) : null}
    </div>
  )
}
