// apps/web/src/integrations/meta_ads/presenters/accounts.tsx

import { DetailList } from "@/components/tool-ui/detail-list"
import { Badge } from "@/components/ui/badge"
import { parseMetaAdsAccount, type MetaAdsAccount } from "@/integrations/meta_ads/lib/read-models"
import { metaAdsProvider } from "@/integrations/meta_ads/provider"
import { defineIntegrationReadPresenter } from "@/integrations/read-presenter"
import { formatCurrencyAmount } from "@/lib/format"

export const metaAdsAccountsPresenter = defineIntegrationReadPresenter(metaAdsProvider, {
  ariaLabel: "Meta Ads account overview",
  emptyLabel: "No Meta Ads accounts were queried.",
  heading: "Get Meta Ads accounts",
  progressLabel: "Loading Meta Ads accounts…",
  tool: "meta_ads_get_accounts",
  parseResult: parseMetaAdsAccount,
  render: (account) => {
    const money = (value: string | null) =>
      value === null ? "Not available" : formatCurrencyAmount(value, account.currency)
    return (
      <div className="grid min-w-0 gap-3">
        <div className="flex flex-wrap items-center gap-2">
          {account.name ? <span className="font-medium">{account.name}</span> : null}
          <Badge variant={account.status.toLowerCase() === "active" ? "success" : "outline"}>
            {account.status}
          </Badge>
        </div>
        {account.disable_reason ? (
          <p className="text-muted-foreground text-xs">{account.disable_reason}</p>
        ) : null}
        <p className="text-sm">{spendSummary(account)}</p>
        <DetailList
          items={[
            { label: "Currency", value: account.currency },
            { label: "Time zone", value: account.timezone_name ?? "Not available" },
            { label: "Remaining spend cap", value: money(account.spend_cap_remaining) },
            { label: "Balance", value: money(account.balance) },
            { label: "Minimum daily budget", value: money(account.min_daily_budget) },
          ]}
        />
      </div>
    )
  },
})

function spendSummary(account: MetaAdsAccount): string {
  const spent =
    account.amount_spent === null
      ? "Amount spent not available"
      : `${formatCurrencyAmount(account.amount_spent, account.currency)} spent`
  if (account.spend_cap === null) return `${spent}; no spend cap`
  const cap = `${formatCurrencyAmount(account.spend_cap, account.currency)} cap`
  return account.amount_spent === null ? `${spent}; ${cap}` : `${spent} of ${cap}`
}
