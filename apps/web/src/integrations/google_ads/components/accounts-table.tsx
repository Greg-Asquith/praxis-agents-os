// apps/web/src/integrations/google_ads/components/accounts-table.tsx

import { DataTable, type DataColumn, type DataRow } from "@/components/ui/data-table"
import type { GoogleAdsAccountOverview } from "@/integrations/google_ads/lib/accounts"
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
  { hidden: true, key: "manager", kind: "text", label: "Manager Account" },
  { hidden: true, key: "auto_tagging", kind: "text", label: "Auto-Tagging" },
]
const MONEY_KEYS = new Set(["cost_today", "cost_this_month"])
const ACCOUNT_NOUN = ["account", "accounts"] as const

// Money stays in each account's own currency, so the table never sums across accounts.
export function GoogleAdsAccountsTable({
  accounts,
  failures,
}: {
  accounts: GoogleAdsAccountOverview[]
  failures: GoogleAdsAccountFailure[]
}) {
  const rows: DataRow[] = accounts.map((account) => ({
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
  return (
    <div className="grid min-w-0 gap-3">
      {rows.length > 0 ? (
        <DataTable
          columns={COLUMNS}
          exportFilename="google-ads-accounts.csv"
          pageSize={25}
          renderCell={(column, row) => moneyCell(column, row)}
          rowNoun={ACCOUNT_NOUN}
          rows={rows}
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

function moneyCell(column: DataColumn, row: DataRow) {
  if (!MONEY_KEYS.has(column.key)) return null
  const value = row[column.key]
  const currency = row["currency"]
  if (typeof value !== "string" || typeof currency !== "string") {
    return <span className="text-muted-foreground">Not available</span>
  }
  return <span className="tabular-nums">{formatCurrencyAmount(value, currency)}</span>
}

function yesNo(value: boolean | null): string {
  return value === null ? "Unknown" : value ? "Yes" : "No"
}
