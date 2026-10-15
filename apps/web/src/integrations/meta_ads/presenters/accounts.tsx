// apps/web/src/integrations/meta_ads/presenters/accounts.tsx

import { Badge } from "@/components/ui/badge"
import { parseMetaAdsAccount } from "@/integrations/meta_ads/lib/read-models"
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
    const spent = Number(account.amount_spent)
    const cap = Number(account.spend_cap)
    const used =
      account.amount_spent !== null && account.spend_cap !== null && cap > 0
        ? Math.min(100, Math.max(0, Math.round((spent / cap) * 100)))
        : null
    const facts = [
      { label: "Balance Due", value: money(account.balance) },
      { label: "Minimum Daily Budget", value: money(account.min_daily_budget) },
      { label: "Currency", value: account.currency },
      { label: "Time Zone", value: account.timezone_name ?? "Not available" },
    ]
    return (
      <div className="grid min-w-0 gap-3">
        <div className="flex flex-wrap items-center gap-2">
          {account.name ? <span className="text-base font-semibold">{account.name}</span> : null}
          <Badge variant={account.status.toLowerCase() === "active" ? "success" : "outline"}>
            {account.status}
          </Badge>
        </div>
        {account.disable_reason ? (
          <p className="text-muted-foreground text-sm">{account.disable_reason}</p>
        ) : null}
        <div className="grid gap-1.5">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 text-sm">
            <span>
              <strong className="text-xl font-semibold tabular-nums">
                {account.amount_spent === null ? "Not available" : money(account.amount_spent)}
              </strong>
              {account.amount_spent === null
                ? " amount spent"
                : account.spend_cap === null
                  ? " spent, no spend cap"
                  : ` spent of the ${money(account.spend_cap)} spend cap`}
            </span>
            {account.spend_cap_remaining === null ? null : (
              <span
                className={
                  used !== null && used >= 80 ? "text-warning-text font-semibold" : "font-semibold"
                }
              >
                {money(account.spend_cap_remaining)} left
              </span>
            )}
          </div>
          {used === null ? null : (
            <div
              aria-label="Spend cap used"
              aria-valuemax={100}
              aria-valuemin={0}
              aria-valuenow={used}
              className="bg-muted h-1.5 overflow-hidden rounded-full"
              role="meter"
            >
              <div
                className={used >= 80 ? "bg-warning h-full" : "bg-primary h-full"}
                style={{ width: `${String(used)}%` }}
              />
            </div>
          )}
        </div>
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {facts.map((fact) => (
            <div key={fact.label} className="grid min-w-0 gap-0.5">
              <dt className="text-muted-foreground text-sm">{fact.label}</dt>
              <dd className="text-sm font-semibold wrap-anywhere tabular-nums">{fact.value}</dd>
            </div>
          ))}
        </dl>
      </div>
    )
  },
})
