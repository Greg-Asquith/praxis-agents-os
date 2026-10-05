// apps/web/src/integrations/meta_ads/components/budget-change.tsx

import { MetaAdsApprovalSection } from "@/integrations/meta_ads/components/approval-section"
import {
  MetaAdsManagerLink,
  MetaAdsObjectCard,
} from "@/integrations/meta_ads/components/object-card"
import {
  MetaAdsOutcomeTable,
  type MetaAdsOutcomeRow,
} from "@/integrations/meta_ads/components/outcome-table"
import { adsManagerObjectUrl } from "@/integrations/meta_ads/lib/ads-manager-link"
import {
  BUDGET_OBJECT_TITLES,
  budgetChangeLine,
  budgetKindLabel,
  budgetMoney,
  budgetNotes,
  type BudgetChangeArgs,
  type BudgetChangeResult,
} from "@/integrations/meta_ads/lib/budget-change"
import { formatPercentageChange } from "@/lib/format"
import { isRecord } from "@/lib/guards"

export function BudgetApprovalSummary({ args }: { args: BudgetChangeArgs }) {
  const count = args.changes.length
  return (
    <MetaAdsApprovalSection
      ariaLabel="Proposed budget changes"
      tone="spend"
      warning="Budget changes take effect straight away and change what you spend."
      countLine={`${String(count)} ${count === 1 ? "budget" : "budgets"}`}
    >
      {args.changes.map((change) => (
        <MetaAdsObjectCard
          key={`${change.type}:${change.id}`}
          title={change.name}
          typeLabel={BUDGET_OBJECT_TITLES[change.type]}
          meta={[change.scope, `${budgetKindLabel(change.kind)}: ${budgetChangeLine(change)}`]
            .filter(Boolean)
            .join(" · ")}
          notes={budgetNotes(change)}
          href={adsManagerObjectUrl(change.type, change.accountId, change.id)}
        />
      ))}
    </MetaAdsApprovalSection>
  )
}

export function BudgetOutcome({ result }: { result: BudgetChangeResult }) {
  const money = (amount: string | null) => (amount ? budgetMoney(amount, result.currency) : "—")
  const rows: (MetaAdsOutcomeRow & { href: string | null })[] = result.budgets.map((row) => ({
    name: row.name,
    type: BUDGET_OBJECT_TITLES[row.type],
    budget: budgetKindLabel(row.kind),
    before: money(row.previousAmount),
    requested: money(row.requestedAmount),
    after: row.outcome === "failed" ? "—" : money(row.amount),
    change: formatPercentageChange(Number(row.previousAmount), Number(row.requestedAmount)),
    outcome: row.outcome,
    details: row.message ?? "",
    errorCode: row.errorCode,
    href: adsManagerObjectUrl(row.type, result.accountId, row.id),
  }))
  return (
    <MetaAdsOutcomeTable
      columns={[
        { key: "name", kind: "text", label: "Name" },
        { key: "type", kind: "text", label: "Type" },
        { key: "budget", kind: "text", label: "Budget" },
        { key: "before", kind: "text", label: "Before", align: "right" },
        { key: "requested", kind: "text", label: "Requested", align: "right" },
        { key: "after", kind: "text", label: "After", align: "right" },
        { key: "change", kind: "text", label: "Change", align: "right" },
      ]}
      rows={rows}
      exportFilename="meta-ads-budgets.csv"
      renderCell={(column, row) =>
        column.key === "name" && isRecord(row) && typeof row["href"] === "string" ? (
          <span className="grid gap-0.5">
            <span className="wrap-anywhere">{String(row["name"])}</span>
            <MetaAdsManagerLink href={row["href"]} />
          </span>
        ) : null
      }
    />
  )
}
