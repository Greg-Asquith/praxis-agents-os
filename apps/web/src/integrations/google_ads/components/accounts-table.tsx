// apps/web/src/integrations/google_ads/components/accounts-table.tsx

import { Badge } from "@/components/ui/badge"
import {
  DataTable,
  type DataColumn,
  type DataRow,
  type DataTableTab,
} from "@/components/ui/data-table"
import type {
  GoogleAdsAccountBilling,
  GoogleAdsAccountOverview,
  GoogleAdsBillingState,
} from "@/integrations/google_ads/lib/accounts"
import { formatCurrencyAmount, formatGoogleAdsAccountId } from "@/lib/format"

export type GoogleAdsAccountFailure = { displayName: string; message: string }

const COLUMNS: DataColumn[] = [
  { key: "name", kind: "text", label: "Account" },
  { key: "customer_id", kind: "id", label: "Account ID" },
  { key: "status", kind: "status", label: "Status" },
  { key: "currency", kind: "text", label: "Currency" },
  { key: "time_zone", kind: "text", label: "Time Zone" },
  { align: "right", key: "cost_today", kind: "number", label: "Today" },
  { align: "right", key: "cost_this_month", kind: "number", label: "This Month" },
  { align: "right", key: "limit_left", kind: "number", label: "Limit Left" },
  { key: "billing", kind: "text", label: "Billing" },
  { hidden: true, key: "spending_limit", kind: "number", label: "Spending Limit" },
  { hidden: true, key: "served", kind: "number", label: "Served Spend" },
  { hidden: true, key: "limit_ends", kind: "text", label: "Limit Ends" },
  { hidden: true, key: "payer", kind: "text", label: "Paid By" },
  { hidden: true, key: "manager", kind: "text", label: "Manager Account" },
  { hidden: true, key: "auto_tagging", kind: "text", label: "Auto-Tagging" },
  { hidden: true, key: "payments_account_id", kind: "id", label: "Payments Account ID" },
  { hidden: true, key: "billing_setup_id", kind: "id", label: "Billing Setup ID" },
  { hidden: true, key: "account_budget_id", kind: "id", label: "Spending Limit ID" },
]
const MONEY_KEYS = new Set([
  "cost_today",
  "cost_this_month",
  "limit_left",
  "spending_limit",
  "served",
])
const ACCOUNT_NOUN = ["account", "accounts"] as const
const BILLING: Record<
  GoogleAdsBillingState,
  { attention: boolean; label: string; variant: "success" | "warning" | "destructive" | "outline" }
> = {
  active: { attention: false, label: "Active", variant: "success" },
  limit_reached: { attention: true, label: "Limit Reached", variant: "destructive" },
  no_active_limit: { attention: true, label: "No Spending Limit", variant: "destructive" },
  not_monthly_invoicing: { attention: false, label: "Managed in Google Ads", variant: "outline" },
  running_low: { attention: true, label: "Low Limit", variant: "warning" },
  setup_pending: { attention: true, label: "Setup Pending", variant: "warning" },
}
const TABS: DataTableTab[] = [
  { id: "all", label: "All", match: () => true },
  {
    hideWhenEmpty: true,
    id: "attention",
    label: "Needs Attention",
    match: (row) => row["attention"] === true,
  },
]

// Money stays in each account's own currency, so the table never sums across accounts.
export function GoogleAdsAccountsTable({
  accounts,
  failures,
}: {
  accounts: GoogleAdsAccountOverview[]
  failures: GoogleAdsAccountFailure[]
}) {
  const rows: DataRow[] = accounts.map((account) => ({
    ...billingCells(account.billing),
    attention:
      account.status === "SUSPENDED" ||
      (account.billing !== null && BILLING[account.billing.state].attention),
    auto_tagging: yesNo(account.autoTaggingEnabled),
    cost_this_month: account.costThisMonth,
    cost_today: account.costToday,
    currency: account.currency,
    customer_id: formatGoogleAdsAccountId(account.customerId),
    manager: yesNo(account.manager),
    name: account.name ?? formatGoogleAdsAccountId(account.customerId),
    status: account.status,
    time_zone: account.timeZone,
  }))
  const hasLimit = accounts.some((account) => account.billing?.activeLimit)
  return (
    <div className="grid min-w-0 gap-3">
      {rows.length > 0 ? (
        <DataTable
          columns={COLUMNS}
          exportFilename="google-ads-accounts.csv"
          pageSize={25}
          renderCell={renderCell}
          rowNoun={ACCOUNT_NOUN}
          rows={rows}
          summary={
            hasLimit ? (
              <span>Limit Left is the spending limit minus served spend, before invoicing.</span>
            ) : null
          }
          tabs={TABS}
        />
      ) : null}
      {failures.length > 0 ? (
        <ul aria-label="Accounts that couldn't be read" className="grid gap-1 text-sm">
          {failures.map((failure) => (
            <li className="text-destructive wrap-anywhere" key={failure.displayName}>
              Couldn&apos;t read {failure.displayName}: {failure.message}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

function billingCells(billing: GoogleAdsAccountBilling | null): DataRow {
  const limit = billing?.activeLimit ?? null
  return {
    account_budget_id: limit?.accountBudgetId ?? null,
    billing: billing ? BILLING[billing.state].label : null,
    billing_pending: (billing?.pendingChanges.length ?? 0) > 0,
    billing_setup_id: billing?.billingSetupId ?? null,
    billing_state: billing?.state ?? null,
    limit_ends: limit ? (limit.ends?.slice(0, 10) ?? "No end date") : null,
    limit_left: limit ? (limit.left ?? "No Limit") : null,
    payer: billing?.paymentsAccountName ?? billing?.paymentsProfileName ?? null,
    payments_account_id: billing?.paymentsAccountId ?? null,
    served: limit?.served ?? null,
    spending_limit: limit ? (limit.limit ?? "No Limit") : null,
  }
}

function renderCell(column: DataColumn, row: DataRow) {
  if (column.key === "billing") return billingCell(row)
  if (!MONEY_KEYS.has(column.key)) return null
  const value = row[column.key]
  const currency = row["currency"]
  if (value === "No Limit") return <span>No Limit</span>
  if (typeof value !== "string" || typeof currency !== "string") {
    return <span className="text-muted-foreground">Not available</span>
  }
  return <span className="tabular-nums">{formatCurrencyAmount(value, currency)}</span>
}

function billingCell(row: DataRow) {
  const state = row["billing_state"]
  if (!isBillingState(state)) return <span className="text-muted-foreground">Not available</span>
  const billing = BILLING[state]
  return (
    <span className="grid justify-items-start gap-0.5">
      <Badge variant={billing.variant}>{billing.label}</Badge>
      {row["billing_pending"] === true ? (
        <span className="text-muted-foreground text-xs">
          Change waiting for Google&apos;s review
        </span>
      ) : null}
    </span>
  )
}

function isBillingState(value: unknown): value is GoogleAdsBillingState {
  return typeof value === "string" && Object.hasOwn(BILLING, value)
}

function yesNo(value: boolean | null): string {
  return value === null ? "Unknown" : value ? "Yes" : "No"
}
